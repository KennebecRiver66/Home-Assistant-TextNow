"""The TextNow integration."""
from __future__ import annotations

import logging
import os

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.loader import async_get_integration
from homeassistant.util import slugify

from .const import (
    CONF_ENTITY_IDS_MIGRATED,
    COOKIE_HELP_URL,
    DEVICE_NAME,
    DOMAIN,
)
from .coordinator import TextNowDataUpdateCoordinator
from .storage import TextNowStorage

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Panel configuration
PANEL_URL = "/textnow_panel"
PANEL_ICON = "mdi:message-text"
PANEL_TITLE = "TextNow"

SERVICE_SEND = "send"
SERVICE_SEND_MENU = "send_menu"

DATA_WEBSOCKET_REGISTERED = "_websocket_registered"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up TextNow from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = TextNowDataUpdateCoordinator(hass, entry)
    # Failures here reach Home Assistant instead of being logged and dropped:
    # an expired session becomes a reauth prompt, a network hiccup a retry.
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Register the TextNow device explicitly so device triggers work reliably
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=DEVICE_NAME,
        manufacturer="TextNow",
        model="SMS Integration",
        serial_number=coordinator.username or None,
    )

    await _async_migrate_entity_ids(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async_setup_services(hass)
    async_setup_websocket_api(hass)

    try:
        await async_register_panel(hass)
    except Exception:  # noqa: BLE001 - the panel is cosmetic
        _LOGGER.warning(
            "The TextNow sidebar panel could not be registered; "
            "sensors and services are unaffected",
            exc_info=True,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator is not None:
            await coordinator.async_shutdown()

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up the repair item when an account is removed."""
    ir.async_delete_issue(hass, DOMAIN, f"expired_session_{entry.entry_id}")


async def _async_migrate_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Give contact sensors short entity IDs, once per account.

    Older releases built the entity ID from the device name and a "TextNow"
    prefixed entity name, which produced IDs such as
    sensor.sms_text_messages_textnow_textnow_sam.
    """
    if entry.data.get(CONF_ENTITY_IDS_MIGRATED):
        return

    registry = er.async_get(hass)
    contacts = await TextNowStorage(hass, entry.entry_id).async_get_contacts()

    for contact_id, contact in contacts.items():
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"textnow_{contact_id}"
        )
        if entity_id is None:
            continue

        name = contact.get("name") or contact_id
        wanted = f"sensor.{slugify(f'{DEVICE_NAME} {name}')}"
        if entity_id == wanted or registry.async_get(wanted) is not None:
            continue

        _LOGGER.info("Renaming TextNow sensor %s to %s", entity_id, wanted)
        registry.async_update_entity(entity_id, new_entity_id=wanted)

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_ENTITY_IDS_MIGRATED: True}
    )


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register the TextNow sidebar panel."""
    # Check if panel is already registered
    if DOMAIN in hass.data.get("frontend_panels", {}):
        return

    panel_path = os.path.join(os.path.dirname(__file__), "frontend")

    # The integration version busts the browser cache after an update. Reading
    # it from the loader avoids opening manifest.json inside the event loop.
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version or "0")

    await hass.http.async_register_static_paths(
        [StaticPathConfig(PANEL_URL, panel_path, cache_headers=False)]
    )

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="textnow-panel",
        frontend_url_path=DOMAIN,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=f"{PANEL_URL}/textnow-panel.js?v={version}",
        embed_iframe=False,
        require_admin=False,
        config={"help_url": COOKIE_HELP_URL, "version": version},
    )

    _LOGGER.debug("TextNow panel registered")


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register the WebSocket commands used by the sidebar panel."""
    if hass.data[DOMAIN].get(DATA_WEBSOCKET_REGISTERED):
        return

    from .websocket import async_setup as async_setup_websocket

    async_setup_websocket(hass)
    hass.data[DOMAIN][DATA_WEBSOCKET_REGISTERED] = True


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the TextNow services.

    Services are registered once for the integration and resolve the account
    to use per call, so reloading one account cannot leave a stale handler
    behind.
    """
    if hass.services.has_service(DOMAIN, SERVICE_SEND):
        return

    from .services import (
        async_resolve_coordinator,
        async_send_menu,
        async_send_message,
        SERVICE_SEND_SCHEMA,
        SERVICE_SEND_MENU_SCHEMA,
    )

    async def send_message_service(call: ServiceCall) -> None:
        """Handle send message service call."""
        coordinator = await async_resolve_coordinator(hass, call.data)
        await async_send_message(hass, coordinator, call.data)

    async def send_menu_service(call: ServiceCall) -> dict:
        """Handle send menu service call."""
        coordinator = await async_resolve_coordinator(hass, call.data)
        return await async_send_menu(hass, coordinator, call.data)

    hass.services.async_register(
        DOMAIN, SERVICE_SEND, send_message_service, schema=SERVICE_SEND_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MENU,
        send_menu_service,
        schema=SERVICE_SEND_MENU_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
