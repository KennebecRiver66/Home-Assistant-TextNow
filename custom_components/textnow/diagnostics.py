"""Diagnostics for the TextNow integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_COOKIES,
    CONF_KEEPALIVE_MESSAGE,
    CONF_KEEPALIVE_PHONE,
    CONF_POLLING_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)
from .coordinator import TextNowDataUpdateCoordinator
from .storage import TextNowStorage

TO_REDACT = {
    CONF_COOKIES,
    CONF_KEEPALIVE_MESSAGE,
    CONF_KEEPALIVE_PHONE,
    CONF_USERNAME,
    "allowed_phones",
    "connect_sid",
    "csrf",
    "xsrf_token",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Cookies, the username, contact names and phone numbers are left out; what
    remains is the state needed to understand a connection problem.
    """
    coordinator: TextNowDataUpdateCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    stored = await TextNowStorage(hass, entry.entry_id).async_load()

    diagnostics: dict[str, Any] = {
        "entry": {
            "version": entry.version,
            "state": entry.state.value,
            "polling_interval": entry.data.get(CONF_POLLING_INTERVAL),
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            # Names only: which cookies were pasted matters, the values do not.
            "cookie_names": sorted(entry.data.get(CONF_COOKIES) or {}),
        },
        "storage": {
            "contact_count": len(stored.get("contacts") or {}),
            "pending_conversations": len(stored.get("pending") or {}),
            "processed_message_ids": len(stored.get("processed_message_ids") or ()),
            "history_adopted": bool(stored.get("history_adopted")),
        },
    }

    if coordinator is None:
        diagnostics["coordinator"] = None
        return diagnostics

    last_error = coordinator.last_exception
    diagnostics["coordinator"] = {
        "last_update_success": coordinator.last_update_success,
        "auth_failed": coordinator.auth_failed,
        "last_success": coordinator.last_success,
        "update_interval_seconds": (
            coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None
        ),
        "last_error_type": type(last_error).__name__ if last_error else None,
        "last_error": str(last_error) if last_error else None,
        "keepalive": {
            "enabled": bool(coordinator.keepalive_phone),
            "days": coordinator.keepalive_days,
            "last_outbound": coordinator.last_outbound,
            "due_at": coordinator.keepalive_due_at,
        },
    }
    return diagnostics
