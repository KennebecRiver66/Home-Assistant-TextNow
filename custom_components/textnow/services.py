"""Services for TextNow integration."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_MESSAGE,
    ATTR_TARGET,
    ATTR_TITLE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EVENT_REPLY_PARSED,
    ATTR_PHONE,
    ATTR_CONTACT_ID,
    DEFAULT_MENU_TIMEOUT,
    DEFAULT_NUMBER_FORMAT,
)
from .coordinator import TextNowDataUpdateCoordinator
from .phone_utils import format_phone_number, validate_phone_number
from .storage import TextNowStorage

_LOGGER = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=60)

SERVICE_SEND_SCHEMA = vol.Schema(
    {
        vol.Optional("message", default=""): str,
        vol.Optional("contact_id"): str,  # Entity ID from dropdown (if empty, uses trigger sender)
        vol.Optional("phone"): str,  # Direct phone number (legacy)
        vol.Optional("mms_image"): str,  # File path from file selector
        vol.Optional("voice_audio"): str,  # File path from file selector
    }
)

SERVICE_SEND_MENU_SCHEMA = vol.Schema(
    {
        vol.Optional("contact_id"): str,  # Entity ID from dropdown (if empty, uses trigger sender)
        vol.Required("options"): str,  # Multiline text, one option per line
        vol.Optional("header"): str,  # Header text (if provided, shown before options)
        vol.Optional("footer"): str,  # Footer text (if provided, shown after options)
        vol.Optional("timeout", default=DEFAULT_MENU_TIMEOUT): vol.All(
            vol.Coerce(int), vol.Range(min=5, max=3600)
        ),
        vol.Optional("number_format", default=DEFAULT_NUMBER_FORMAT): str,
    }
)

# notify.textnow takes Home Assistant's notification payload rather than this
# integration's own, so an automation or blueprint written for another SMS
# integration works by changing nothing but the service name.
NOTIFY_SEND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Optional(ATTR_TARGET): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_DATA): dict,
    }
)

# Shown in Developer tools and the automation editor. Services in the notify
# domain cannot be described from this integration's services.yaml, which only
# describes its own domain, so the description is registered from code.
NOTIFY_SERVICE_DESCRIPTION: dict[str, Any] = {
    "name": "Send a notification with TextNow",
    "description": "Sends a text message through TextNow.",
    "fields": {
        ATTR_MESSAGE: {
            "required": True,
            "example": "The garage door has been open for 10 minutes.",
            "selector": {"text": {"multiline": True}},
        },
        ATTR_TITLE: {
            "example": "Home Assistant",
            "selector": {"text": None},
        },
        ATTR_TARGET: {
            "example": "(555) 123-4567",
            "selector": {"object": None},
        },
        ATTR_DATA: {
            "example": '{"image": "/config/www/photo.jpg"}',
            "selector": {"object": None},
        },
    },
}

# What other integrations call an attachment, in the order they are looked for.
# media_url is Twilio's, image is the companion app's.
NOTIFY_IMAGE_KEYS = ("mms_image", "image", "media_url", "media", "attachment")
NOTIFY_AUDIO_KEYS = ("voice_audio", "audio", "voice")


@callback
def async_get_coordinators(
    hass: HomeAssistant,
) -> list[TextNowDataUpdateCoordinator]:
    """Return the coordinators of every loaded TextNow account."""
    return [
        value
        for value in hass.data.get(DOMAIN, {}).values()
        if isinstance(value, TextNowDataUpdateCoordinator)
    ]


async def async_resolve_coordinator(
    hass: HomeAssistant, data: dict[str, Any]
) -> TextNowDataUpdateCoordinator:
    """Return the account a service call should use."""
    coordinators = async_get_coordinators(hass)

    if not coordinators:
        raise ServiceValidationError(
            "No TextNow account is connected. Check Settings > Devices & "
            "services > TextNow; the account may need new cookies."
        )

    if len(coordinators) == 1:
        return coordinators[0]

    # With several accounts, use the one that knows the contact involved.
    last_trigger = hass.data.get(DOMAIN, {}).get("last_trigger_contact") or {}
    contact_id = _normalize_contact_id(data.get("contact_id")) or _normalize_contact_id(
        last_trigger.get("contact_id")
    )

    if contact_id:
        for coordinator in coordinators:
            storage = TextNowStorage(hass, coordinator.entry.entry_id)
            if contact_id in await storage.async_get_contacts():
                return coordinator

    return coordinators[0]


def _normalize_contact_id(contact_id: str | None) -> str:
    """Return the storage contact id for a contact id or entity id."""
    if not contact_id:
        return ""
    if contact_id.startswith("sensor.textnow_"):
        return contact_id.removeprefix("sensor.textnow_")
    return contact_id


async def async_send_message(
    hass: HomeAssistant, coordinator: TextNowDataUpdateCoordinator, data: dict[str, Any]
) -> None:
    """Handle send message service call.

    Sends messages in order: SMS first, MMS second, voice message last.
    Only sends what is provided in the service call.
    """
    phone = await _resolve_phone_from_contact(hass, coordinator, data)

    message = data.get("message", "")
    mms_image = data.get("mms_image")
    voice_audio = data.get("voice_audio")

    if not message and not mms_image and not voice_audio:
        raise ServiceValidationError(
            "Nothing to send: provide a message, an image or an audio file."
        )

    if message:
        await coordinator.send_message(phone, message)
        _LOGGER.debug("Sent SMS to %s", phone)
        _async_notify_sent(hass, phone)

    if mms_image:
        file_data = await _async_read_media(hass, mms_image)
        filename = os.path.basename(mms_image) or "image.jpg"
        await coordinator.send_mms(phone, message, file_data, filename)
        _LOGGER.debug("Sent MMS to %s", phone)
        _async_notify_sent(hass, phone)

    if voice_audio:
        file_data = await _async_read_media(hass, voice_audio)
        await coordinator.send_voice_message(phone, file_data)
        _LOGGER.debug("Sent voice message to %s", phone)
        _async_notify_sent(hass, phone)


async def async_notify(
    hass: HomeAssistant, coordinator: TextNowDataUpdateCoordinator, data: dict[str, Any]
) -> None:
    """Handle a notify.textnow call.

    Translates Home Assistant's notification payload into the send the
    textnow.send service performs, so the two cannot drift apart. Every target
    is attempted even if one of them fails, because a number that is no longer
    in service should not silence the notification for everyone else.
    """
    extras = data.get(ATTR_DATA) or {}
    payload: dict[str, Any] = {
        "message": notify_text(data.get(ATTR_MESSAGE, ""), data.get(ATTR_TITLE)),
        "mms_image": _first_value(extras, NOTIFY_IMAGE_KEYS),
        "voice_audio": _first_value(extras, NOTIFY_AUDIO_KEYS),
    }

    targets = data.get(ATTR_TARGET) or []
    if not targets:
        # No target replies to the message that triggered the automation, the
        # same as textnow.send with no contact.
        await async_send_message(hass, coordinator, payload)
        return

    first_error: Exception | None = None

    for target in targets:
        try:
            destination = await _async_resolve_target(hass, coordinator, target)
            await async_send_message(hass, coordinator, {**payload, **destination})
        except Exception as err:  # noqa: BLE001 - one bad target is not all of them
            if len(targets) == 1:
                raise
            _LOGGER.error("TextNow could not notify %s: %s", target, err)
            if first_error is None:
                first_error = err

    if first_error is not None:
        raise first_error


def notify_text(message: str, title: str | None) -> str:
    """Return the text to send for a message and title.

    A text message has no title field, so a title becomes the first line. That
    is what the SMS integrations this replaces do, and it keeps the title of a
    shared blueprint visible instead of dropping it.
    """
    title = (title or "").strip()
    message = message or ""
    if not title:
        return message
    if not message:
        return title
    return f"{title}\n{message}"


def _first_value(extras: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """Return the first usable attachment under any of the given keys."""
    for key in keys:
        value = extras.get(key)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def _async_resolve_target(
    hass: HomeAssistant, coordinator: TextNowDataUpdateCoordinator, target: str
) -> dict[str, str]:
    """Return the send payload for one notify target.

    A target may be a phone number, a contact's name, its storage id or its
    sensor entity id, because an automation written by hand will use whichever
    of those the author had in front of them.
    """
    target = str(target or "").strip()
    if not target:
        raise ServiceValidationError(
            "A notify target was empty. Use a 10-digit phone number or the "
            "name of a TextNow contact."
        )

    if validate_phone_number(target):
        return {"phone": format_phone_number(target)}

    if target.startswith("sensor."):
        return {ATTR_CONTACT_ID: target}

    contacts = await TextNowStorage(
        hass, coordinator.entry.entry_id
    ).async_get_contacts()

    if target not in contacts:
        folded = target.casefold()
        for contact_id, contact in contacts.items():
            if str(contact.get("name", "")).casefold() == folded:
                return {ATTR_CONTACT_ID: contact_id}

    # Unknown either way: the shared resolver raises the error that lists the
    # contacts this account does know about.
    return {ATTR_CONTACT_ID: target}


async def _async_read_media(hass: HomeAssistant, file_path: str) -> bytes:
    """Return the bytes of a local file or an http(s) URL."""
    if file_path.startswith(("http://", "https://")):
        return await _async_download_media(hass, file_path)

    local_path = await hass.async_add_executor_job(_resolve_file_path, hass, file_path)
    if local_path is None:
        raise ServiceValidationError(
            f"Could not find the file '{file_path}'. Use a path such as "
            "/config/www/photo.jpg, /local/photo.jpg or an http(s) URL."
        )

    def _read() -> bytes:
        with open(local_path, "rb") as file:
            return file.read()

    try:
        return await hass.async_add_executor_job(_read)
    except OSError as err:
        raise ServiceValidationError(
            f"Could not read the file '{file_path}': {err}"
        ) from err


async def _async_download_media(hass: HomeAssistant, url: str) -> bytes:
    """Download media to attach to a message."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    session = async_get_clientsession(hass)
    try:
        async with session.get(url, timeout=DOWNLOAD_TIMEOUT) as response:
            if response.status != 200:
                raise ServiceValidationError(
                    f"Downloading '{url}' returned HTTP {response.status}."
                )
            return await response.read()
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise ServiceValidationError(
            f"Could not download '{url}': {err}"
        ) from err


def _resolve_file_path(hass: HomeAssistant, file_path: str) -> str | None:
    """Resolve a media path to a file on disk.

    Handles /local/ (the www folder), /config/ paths, absolute paths and
    paths relative to the configuration directory. Runs in an executor
    because it touches the filesystem.
    """
    if not file_path:
        return None

    file_path = file_path.replace("\\", "/")
    candidates: list[str] = []

    if file_path.startswith("/local/"):
        candidates.append(
            os.path.join(hass.config.path("www"), file_path[len("/local/"):])
        )
    elif file_path.startswith("/config/"):
        candidates.append(
            os.path.join(hass.config.config_dir, file_path[len("/config/"):])
        )
    elif os.path.isabs(file_path):
        candidates.append(file_path)
    else:
        candidates.append(os.path.join(hass.config.config_dir, file_path))

    candidates.append(file_path)

    for candidate in candidates:
        resolved = os.path.normpath(candidate)
        if os.path.isfile(resolved):
            return resolved

    _LOGGER.debug("No file found for %s (tried %s)", file_path, candidates)
    return None


async def _resolve_phone_from_contact(
    hass: HomeAssistant, coordinator: TextNowDataUpdateCoordinator, data: dict[str, Any]
) -> str:
    """Return the phone number a service call should send to.

    If contact_id is provided that contact is used, otherwise the reply goes
    to whoever sent the message that triggered the automation.
    """
    contact_id = data.get("contact_id")
    phone = data.get("phone")

    if not contact_id:
        if phone:
            return phone

        last_trigger = hass.data.get(DOMAIN, {}).get("last_trigger_contact") or {}
        if last_trigger.get("phone"):
            return str(last_trigger["phone"])
        contact_id = last_trigger.get("contact_id")
        if not contact_id:
            raise ServiceValidationError(
                "No contact was given and no TextNow message has been "
                "received to reply to. Select a contact in the Contact field."
            )

    # An entity id can carry the phone number in its attributes
    if isinstance(contact_id, str) and contact_id.startswith("sensor."):
        state = hass.states.get(contact_id)
        if state and state.attributes.get(ATTR_PHONE):
            return str(state.attributes[ATTR_PHONE])

    storage_id = _normalize_contact_id(contact_id)
    storage = TextNowStorage(hass, coordinator.entry.entry_id)
    contacts = await storage.async_get_contacts()

    if storage_id in contacts:
        return str(contacts[storage_id]["phone"])

    if contacts:
        known = ", ".join(sorted(contacts))
        raise ServiceValidationError(
            f"Unknown TextNow contact '{contact_id}'. Known contacts: {known}."
        )
    raise ServiceValidationError(
        f"Unknown TextNow contact '{contact_id}'. No contacts are configured "
        "yet; add one in the TextNow panel."
    )


@callback
def _async_notify_sent(hass: HomeAssistant, phone: str) -> None:
    """Tell the contact sensor that a message went out."""
    hass.bus.async_fire(
        f"{DOMAIN}_message_sent",
        {
            "phone": phone,
            "timestamp": dt_util.utcnow().isoformat(),
        },
    )


def _build_menu_text(
    header: str,
    options: list[str],
    footer: str,
    number_format: str = DEFAULT_NUMBER_FORMAT,
) -> str:
    """Build formatted menu text from options.

    Args:
        header: Text before the menu options
        options: List of menu option strings
        footer: Text after the menu options
        number_format: Format string for each option (uses {n} and {option})

    Returns:
        Formatted menu text string
    """
    lines = []

    if header:
        lines.append(header)
        lines.append("")  # Empty line after header

    for idx, option in enumerate(options, start=1):
        formatted_option = number_format.format(n=idx, option=option)
        lines.append(formatted_option)

    if footer:
        lines.append("")  # Empty line before footer
        lines.append(footer)

    return "\n".join(lines)


def _parse_options_text(options_text: str) -> list[str]:
    """Parse multiline options text into a list of options.

    Each non-empty line becomes an option.
    """
    lines = options_text.strip().split("\n")
    return [line.strip() for line in lines if line.strip()]


async def async_send_menu(
    hass: HomeAssistant, coordinator: TextNowDataUpdateCoordinator, data: dict[str, Any]
) -> dict[str, Any]:
    """Handle send menu service call.

    Builds a numbered menu from options, sends it via SMS, and waits for response.
    Returns response data for use with response_variable.
    """
    phone = await _resolve_phone_from_contact(hass, coordinator, data)

    contact_id = data.get("contact_id", "")
    options_text = data.get("options", "")
    header = data.get("header", "")  # Empty if not provided/checked
    footer = data.get("footer", "")  # Empty if not provided/checked
    timeout = data.get("timeout", DEFAULT_MENU_TIMEOUT)
    number_format = data.get("number_format", DEFAULT_NUMBER_FORMAT)

    # Parse options from multiline text
    options = _parse_options_text(options_text)

    if not options:
        raise ServiceValidationError(
            "The menu needs at least one option, one per line."
        )

    # Build menu text
    menu_text = _build_menu_text(header, options, footer, number_format)

    # Register the expectation before sending so a fast reply is not missed
    storage = TextNowStorage(hass, coordinator.entry.entry_id)
    await storage.async_set_pending(
        phone,
        "menu",
        {
            "type": "choice",
            "options": options,
            "created_at": dt_util.utcnow().isoformat(),
            "ttl_seconds": timeout,
        },
    )

    response_future: asyncio.Future[dict[str, Any]] = asyncio.Future()

    @callback
    def handle_reply_event(event) -> None:
        """Handle reply parsed event."""
        event_data = event.data
        event_phone = event_data.get(ATTR_PHONE, "")

        # Check if this reply is for our phone
        if event_phone != phone:
            return

        # Build response data
        response_data = {
            "option": int(
                event_data.get(
                    "response_number", event_data.get("option_index", 0) + 1
                )
            ),
            "option_index": event_data.get("option_index", 0),
            "value": event_data.get("value", ""),
            "raw_text": event_data.get("raw_text", ""),
            "phone": event_phone,
            "contact_id": event_data.get(ATTR_CONTACT_ID, contact_id),
            "timed_out": False,
        }

        # Resolve the future if not already done
        if not response_future.done():
            response_future.set_result(response_data)

    unsub_callback = hass.bus.async_listen(EVENT_REPLY_PARSED, handle_reply_event)

    try:
        await coordinator.send_message(phone, menu_text)
        _LOGGER.debug("Sent menu to %s with %d options", phone, len(options))
        _async_notify_sent(hass, phone)

        # Wait for response with timeout
        result = await asyncio.wait_for(response_future, timeout=timeout)
        _LOGGER.debug("Received response from %s: option %s", phone, result.get("option"))
        return result

    except asyncio.TimeoutError:
        _LOGGER.debug(
            "Menu response timed out for %s after %d seconds", phone, timeout
        )
        return {
            "option": 0,
            "option_index": -1,
            "value": "",
            "raw_text": "",
            "phone": phone,
            "contact_id": contact_id,
            "timed_out": True,
        }

    finally:
        unsub_callback()
        await storage.async_clear_pending(phone, "menu")
