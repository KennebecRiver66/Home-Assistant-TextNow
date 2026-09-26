"""What the panel's buttons do when an account is stuck.

An expired session stops the config entry loading at all, so there is no
coordinator behind it. Every button on the Connection tab has to do something
useful in that state, because that is exactly when the user presses them.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState

from custom_components.textnow.const import DOMAIN
from custom_components.textnow.websocket import websocket_refresh

# The handlers are registered through Home Assistant's async_response
# decorator, which schedules them on a live connection. The coroutine
# underneath is what holds the behaviour worth testing.
refresh = websocket_refresh.__wrapped__


class _Connection:
    def __init__(self) -> None:
        self.results: list[object] = []
        self.errors: list[tuple[str, str]] = []

    def send_result(self, _id, result) -> None:
        self.results.append(result)

    def send_error(self, _id, code, message) -> None:
        self.errors.append((code, message))


class _ConfigEntries:
    def __init__(self, entry, on_reload=None) -> None:
        self._entry = entry
        self._on_reload = on_reload
        self.reloaded: list[str] = []

    def async_get_entry(self, entry_id):
        return self._entry if entry_id == self._entry.entry_id else None

    async def async_reload(self, entry_id) -> None:
        self.reloaded.append(entry_id)
        if self._on_reload is not None:
            self._on_reload()


class _Hass:
    def __init__(self, entry, data, on_reload=None) -> None:
        self.config_entries = _ConfigEntries(entry, on_reload)
        self.data = data


def _entry(state=ConfigEntryState.SETUP_ERROR, reason="") -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-1",
        domain=DOMAIN,
        state=state,
        reason=reason,
        disabled_by=None,
        async_get_active_flows=lambda hass, sources: [],
    )


class _Coordinator:
    def __init__(self) -> None:
        self.auth_failed = True
        self.last_update_success = False
        self.last_exception = None
        self.rearmed = 0
        self.refreshed = 0

    def async_rearm_polling(self) -> None:
        self.rearmed += 1
        self.auth_failed = False

    async def async_refresh(self) -> None:
        self.refreshed += 1
        self.last_update_success = True


def test_refresh_retries_the_setup_when_the_entry_never_loaded() -> None:
    """Pressing Refresh on a failed account must try again, not report a fault.

    There is no coordinator to poll in this state. Reloading is the only thing
    that can bring the account back, and it is what the button means.
    """
    entry = _entry(reason="TextNow rejected the session (HTTP 401)")
    data = {DOMAIN: {}}
    coordinator = _Coordinator()

    def _loads() -> None:
        entry.state = ConfigEntryState.LOADED
        coordinator.auth_failed = False
        coordinator.last_update_success = True
        data[DOMAIN]["entry-1"] = coordinator

    hass = _Hass(entry, data, on_reload=_loads)
    connection = _Connection()

    asyncio.run(refresh(hass, connection, {"id": 1, "entry_id": "entry-1"}))

    assert hass.config_entries.reloaded == ["entry-1"]
    assert connection.errors == []
    assert connection.results[-1]["status"] == "connected"


def test_refresh_reports_the_reason_when_the_retry_fails_too() -> None:
    """A session that is still dead has to say so rather than look fixed."""
    entry = _entry(reason="TextNow rejected the session (HTTP 401)")
    hass = _Hass(entry, {DOMAIN: {}})
    connection = _Connection()

    asyncio.run(refresh(hass, connection, {"id": 1, "entry_id": "entry-1"}))

    assert hass.config_entries.reloaded == ["entry-1"]
    assert connection.results[-1]["status"] == "reauth_required"
    assert "401" in connection.results[-1]["last_error"]


def test_refresh_re_arms_an_account_that_was_slowed_down() -> None:
    """The escape hatch from the recovery interval, for the impatient."""
    entry = _entry(state=ConfigEntryState.LOADED)
    coordinator = _Coordinator()
    hass = _Hass(entry, {DOMAIN: {"entry-1": coordinator}})
    connection = _Connection()

    asyncio.run(refresh(hass, connection, {"id": 1, "entry_id": "entry-1"}))

    assert coordinator.rearmed == 1
    assert coordinator.refreshed == 1
    assert hass.config_entries.reloaded == []
    assert connection.results[-1]["status"] == "connected"


def test_refresh_on_an_unknown_account_is_an_error() -> None:
    hass = _Hass(_entry(), {DOMAIN: {}})
    connection = _Connection()

    asyncio.run(refresh(hass, connection, {"id": 1, "entry_id": "nope"}))

    assert connection.errors[0][0] == "not_found"
