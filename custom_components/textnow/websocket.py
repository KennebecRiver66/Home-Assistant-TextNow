"""WebSocket API for TextNow panel."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_KEEPALIVE_DAYS,
    CONF_KEEPALIVE_PHONE,
    CONF_POLLING_INTERVAL,
    CONF_USERNAME,
    DEFAULT_KEEPALIVE_DAYS,
    DOMAIN,
)
from .phone_utils import format_phone_number
from .storage import TextNowStorage

_LOGGER = logging.getLogger(__name__)


@callback
def async_setup(hass: HomeAssistant) -> None:
    """Set up WebSocket API."""
    websocket_api.async_register_command(hass, websocket_get_entries)
    websocket_api.async_register_command(hass, websocket_contacts_list)
    websocket_api.async_register_command(hass, websocket_contacts_add)
    websocket_api.async_register_command(hass, websocket_contacts_update)
    websocket_api.async_register_command(hass, websocket_contacts_delete)
    websocket_api.async_register_command(hass, websocket_send_test)
    websocket_api.async_register_command(hass, websocket_refresh)
    websocket_api.async_register_command(hass, websocket_start_reauth)
    websocket_api.async_register_command(hass, websocket_keepalive_now)


STATUS_CONNECTED = "connected"
STATUS_REAUTH_REQUIRED = "reauth_required"
STATUS_OFFLINE = "offline"
STATUS_DISABLED = "disabled"


def _entry_status(hass: HomeAssistant, entry: ConfigEntry, coordinator: Any) -> str:
    """Return one status for an account, in the order that matters to a user.

    Needing a new sign-in outranks being offline, because it is the only one
    the user can do something about. An expired session stops the entry from
    loading at all, so the state has to be read without a coordinator too.

    Home Assistant's own view of the entry comes first. The coordinator's
    auth_failed is only consulted about a poll that actually failed: as a
    free-standing flag it is a second copy of a truth Home Assistant already
    tracks, and it is the copy that drifts.
    """
    if entry.disabled_by is not None:
        return STATUS_DISABLED
    if (
        entry.state is ConfigEntryState.SETUP_ERROR
        or entry.async_get_active_flows(hass, {SOURCE_REAUTH})
        or (
            coordinator is not None
            and coordinator.auth_failed
            and not coordinator.last_update_success
        )
    ):
        return STATUS_REAUTH_REQUIRED
    if entry.state is ConfigEntryState.SETUP_RETRY:
        return STATUS_OFFLINE
    if entry.state is not ConfigEntryState.LOADED or coordinator is None:
        return STATUS_DISABLED
    if not coordinator.last_update_success:
        return STATUS_OFFLINE
    return STATUS_CONNECTED


def _keepalive_state(entry: ConfigEntry, coordinator: Any) -> dict[str, Any]:
    """Describe the keep-alive for the panel.

    Read from the entry rather than the coordinator so it is still reported
    while the account waits to be signed in again.
    """
    phone = str(entry.data.get(CONF_KEEPALIVE_PHONE) or "")
    last_outbound = getattr(coordinator, "last_outbound", None)
    due_at = getattr(coordinator, "keepalive_due_at", None)
    return {
        "phone": phone,
        "enabled": bool(phone),
        "days": int(entry.data.get(CONF_KEEPALIVE_DAYS) or DEFAULT_KEEPALIVE_DAYS),
        "last_outbound": last_outbound.isoformat() if last_outbound else "",
        "due_at": due_at.isoformat() if due_at else "",
    }


@websocket_api.websocket_command(
    {
        "type": "textnow/get_entries",
    }
)
@websocket_api.async_response
async def websocket_get_entries(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Get all TextNow config entries with their connection state."""
    result = []

    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        last_error = getattr(coordinator, "last_exception", None)
        last_success = getattr(coordinator, "last_success", None)
        interval = getattr(coordinator, "update_interval", None)
        status = _entry_status(hass, entry, coordinator)
        result.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "account": getattr(coordinator, "username", "")
                or entry.data.get(CONF_USERNAME, ""),
                "status": status,
                # The booleans below predate "status" and are kept so an
                # older cached panel keeps working after an update.
                "loaded": entry.state is ConfigEntryState.LOADED,
                "connected": status == STATUS_CONNECTED,
                "needs_reauth": status == STATUS_REAUTH_REQUIRED,
                "last_error": str(last_error) if last_error else "",
                "last_success": last_success.isoformat() if last_success else "",
                "polling_interval": entry.data.get(CONF_POLLING_INTERVAL),
                "current_interval": (
                    int(interval.total_seconds()) if interval else None
                ),
                "keepalive": _keepalive_state(entry, coordinator),
            }
        )

    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        "type": "textnow/refresh",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def websocket_refresh(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Check for messages now instead of waiting for the next poll."""
    entry_id = msg["entry_id"]

    entry = hass.config_entries.async_get_entry(entry_id)
    if not entry or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return

    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is None:
        # An expired session stops the entry loading at all, so there is no
        # coordinator to refresh. Retrying the setup is what this button means
        # in that state: if the session works again the account comes back, and
        # if it does not, Home Assistant re-offers the sign-in prompt.
        await hass.config_entries.async_reload(entry_id)
        coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
        connection.send_result(
            msg["id"],
            {
                "status": _entry_status(hass, entry, coordinator),
                "last_error": str(entry.reason or ""),
            },
        )
        return

    # Re-arm first: an account that has been slowed to the recovery interval
    # should go straight back to normal if this check works, rather than
    # staying slow until the next one.
    coordinator.async_rearm_polling()

    # async_refresh reports through the coordinator rather than raising, so a
    # failed check leaves the panel to show the status it produced.
    await coordinator.async_refresh()
    connection.send_result(
        msg["id"],
        {
            "status": _entry_status(hass, entry, coordinator),
            "last_error": (
                str(coordinator.last_exception) if coordinator.last_exception else ""
            ),
        },
    )


@websocket_api.websocket_command(
    {
        "type": "textnow/start_reauth",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def websocket_start_reauth(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Open the sign-in form for an account.

    Without this the panel could only send the user to the integrations
    page, which shows a reauth prompt when Home Assistant happens to have
    one open and nothing at all when it does not.
    """
    entry_id = msg["entry_id"]

    entry = hass.config_entries.async_get_entry(entry_id)
    if not entry or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return

    # Starting a second one would leave the user with two identical prompts.
    if not entry.async_get_active_flows(hass, {SOURCE_REAUTH}):
        entry.async_start_reauth(hass)

    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        "type": "textnow/keepalive_now",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def websocket_keepalive_now(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send the keep-alive message now instead of waiting for it to be due."""
    entry_id = msg["entry_id"]

    entry = hass.config_entries.async_get_entry(entry_id)
    if not entry or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return

    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_loaded", "This account is not currently loaded"
        )
        return

    if not coordinator.keepalive_phone:
        connection.send_error(
            msg["id"], "not_configured", "No keep-alive number has been set"
        )
        return

    try:
        await coordinator.send_message(
            coordinator.keepalive_phone, coordinator.keepalive_message
        )
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "send_failed", str(err))
        return
    except Exception:
        _LOGGER.exception("Unexpected error sending the TextNow keep-alive message")
        connection.send_error(
            msg["id"],
            "send_failed",
            "Something went wrong while sending. Check the Home Assistant log.",
        )
        return

    connection.send_result(
        msg["id"], {"success": True, "phone": coordinator.keepalive_phone}
    )


@websocket_api.websocket_command(
    {
        "type": "textnow/contacts_list",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def websocket_contacts_list(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List all contacts for an entry."""
    entry_id = msg["entry_id"]
    
    # Verify entry exists
    entry = hass.config_entries.async_get_entry(entry_id)
    if not entry or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return
    
    storage = TextNowStorage(hass, entry_id)
    contacts = await storage.async_get_contacts()
    
    # Format contacts for frontend
    result = []
    for contact_id, contact_data in contacts.items():
        result.append({
            "id": contact_id,
            "name": contact_data.get("name", ""),
            "phone": contact_data.get("phone", ""),
            "enabled": True,  # All contacts are enabled by default
        })
    
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        "type": "textnow/contacts_add",
        vol.Required("entry_id"): str,
        vol.Required("name"): str,
        vol.Required("phone"): str,
    }
)
@websocket_api.async_response
async def websocket_contacts_add(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Add a new contact."""
    entry_id = msg["entry_id"]
    name = msg["name"].strip()
    phone = msg["phone"].strip()
    
    if not name or not phone:
        connection.send_error(msg["id"], "invalid_format", "Name and phone are required")
        return
    
    # Verify entry exists
    entry = hass.config_entries.async_get_entry(entry_id)
    if not entry or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return
    
    # Format phone number
    try:
        formatted_phone = format_phone_number(phone)
    except ValueError as e:
        connection.send_error(msg["id"], "invalid_format", str(e))
        return
    
    storage = TextNowStorage(hass, entry_id)
    
    # Generate contact_id if not provided
    contact_id = f"contact_{name.lower().replace(' ', '_')}"
    contacts = await storage.async_get_contacts()
    counter = 1
    original_id = contact_id
    while contact_id in contacts:
        contact_id = f"{original_id}_{counter}"
        counter += 1
    
    await storage.async_save_contact(contact_id, name, formatted_phone)
    
    # Fire event for sensor update
    hass.bus.async_fire(
        f"{DOMAIN}_contact_added",
        {"contact_id": contact_id, "name": name, "phone": formatted_phone},
    )
    
    connection.send_result(msg["id"], {
        "id": contact_id,
        "name": name,
        "phone": formatted_phone,
        "enabled": True,
    })


@websocket_api.websocket_command(
    {
        "type": "textnow/contacts_update",
        vol.Required("entry_id"): str,
        vol.Required("contact_id"): str,
        vol.Required("name"): str,
        vol.Required("phone"): str,
        vol.Optional("enabled", default=True): bool,
    }
)
@websocket_api.async_response
async def websocket_contacts_update(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Update an existing contact."""
    entry_id = msg["entry_id"]
    contact_id = msg["contact_id"]
    name = msg["name"].strip()
    phone = msg["phone"].strip()
    
    if not name or not phone:
        connection.send_error(msg["id"], "invalid_format", "Name and phone are required")
        return
    
    # Verify entry exists
    entry = hass.config_entries.async_get_entry(entry_id)
    if not entry or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return
    
    storage = TextNowStorage(hass, entry_id)
    contacts = await storage.async_get_contacts()
    
    if contact_id not in contacts:
        connection.send_error(msg["id"], "not_found", "Contact not found")
        return
    
    # Format phone number
    try:
        formatted_phone = format_phone_number(phone)
    except ValueError as e:
        connection.send_error(msg["id"], "invalid_format", str(e))
        return
    
    await storage.async_save_contact(contact_id, name, formatted_phone)
    
    connection.send_result(msg["id"], {
        "id": contact_id,
        "name": name,
        "phone": formatted_phone,
        "enabled": msg.get("enabled", True),
    })


@websocket_api.websocket_command(
    {
        "type": "textnow/contacts_delete",
        vol.Required("entry_id"): str,
        vol.Required("contact_id"): str,
    }
)
@websocket_api.async_response
async def websocket_contacts_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete a contact."""
    entry_id = msg["entry_id"]
    contact_id = msg["contact_id"]
    
    # Verify entry exists
    entry = hass.config_entries.async_get_entry(entry_id)
    if not entry or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return
    
    storage = TextNowStorage(hass, entry_id)
    contacts = await storage.async_get_contacts()
    
    if contact_id not in contacts:
        connection.send_error(msg["id"], "not_found", "Contact not found")
        return
    
    await storage.async_delete_contact(contact_id)
    
    # Fire event for sensor removal
    hass.bus.async_fire(
        f"{DOMAIN}_contact_deleted",
        {"contact_id": contact_id},
    )
    
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        "type": "textnow/send_test",
        vol.Required("entry_id"): str,
        vol.Optional("contact_id"): str,
        vol.Optional("phone"): str,
        vol.Required("message"): str,
    }
)
@websocket_api.async_response
async def websocket_send_test(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send a test message."""
    entry_id = msg["entry_id"]
    contact_id = msg.get("contact_id")
    phone = msg.get("phone")
    message = msg["message"].strip()
    
    if not message:
        connection.send_error(msg["id"], "invalid_format", "Message is required")
        return
    
    # Verify entry exists
    entry = hass.config_entries.async_get_entry(entry_id)
    if not entry or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return
    
    # Get coordinator
    if DOMAIN not in hass.data or entry_id not in hass.data[DOMAIN]:
        connection.send_error(
            msg["id"],
            "not_loaded",
            "This account is waiting to be signed in again, so nothing can be "
            "sent from it yet",
        )
        return
    
    coordinator = hass.data[DOMAIN][entry_id]
    
    # Resolve phone number
    if contact_id:
        storage = TextNowStorage(hass, entry_id)
        contacts = await storage.async_get_contacts()
        if contact_id not in contacts:
            connection.send_error(msg["id"], "not_found", "Contact not found")
            return
        phone = contacts[contact_id]["phone"]
    elif phone:
        # Format phone number if provided directly
        try:
            phone = format_phone_number(phone)
        except ValueError as e:
            connection.send_error(msg["id"], "invalid_format", str(e))
            return
    else:
        connection.send_error(
            msg["id"],
            "invalid_format",
            "Either contact_id or phone must be provided",
        )
        return
    
    # Send message
    try:
        await coordinator.send_message(phone, message)
    except HomeAssistantError as err:
        # TextNow errors already carry text written for the person reading it.
        connection.send_error(msg["id"], "send_failed", str(err))
    except Exception:
        _LOGGER.exception("Unexpected error sending a TextNow message")
        connection.send_error(
            msg["id"],
            "send_failed",
            "Something went wrong while sending. Check the Home Assistant log.",
        )
    else:
        connection.send_result(msg["id"], {"success": True, "phone": phone})

