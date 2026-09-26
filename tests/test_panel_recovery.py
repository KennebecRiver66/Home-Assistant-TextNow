"""What the panel's buttons do when an account is stuck.

An expired session stops the config entry loading at all, so there is no
coordinator behind it. Every button on the Connection tab has to do something
useful in that state, because that is exactly when the user presses them.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.textnow import websocket
from custom_components.textnow.const import DOMAIN
from custom_components.textnow.websocket import websocket_refresh, websocket_start_reauth
from fakes import FakeHass

# The handlers are registered through Home Assistant's async_response
# decorator, which schedules them on a live connection. The coroutine
# underneath is what holds the behaviour worth testing.
refresh = websocket_refresh.__wrapped__
start_reauth = websocket_start_reauth.__wrapped__


class _Connection:
    def __init__(self) -> None:
        self.results: list[Any] = []
        self.errors: list[tuple[str, str]] = []

    def send_result(self, _id, result) -> None:
        self.results.append(result)

    def send_error(self, _id, code, message) -> None:
        self.errors.append((code, message))


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


def _setup(state=ConfigEntryState.SETUP_ERROR, reason="", coordinator=None):
    hass = FakeHass()
    entry = hass.make_entry(state=state, reason=reason)
    hass.data[DOMAIN] = {}
    if coordinator is not None:
        hass.data[DOMAIN][entry.entry_id] = coordinator
    return hass, entry, _Connection()


def _msg(entry_id="entry-1"):
    return {"id": 1, "entry_id": entry_id}


# ------------------------------------------------------------------ refresh


def test_refresh_retries_the_setup_when_the_entry_never_loaded() -> None:
    """Pressing Refresh on a failed account must try again, not report a fault.

    There is no coordinator to poll in this state. Reloading is the only thing
    that can bring the account back, and it is what the button means.
    """
    hass, entry, connection = _setup(reason="TextNow rejected the session (HTTP 401)")
    coordinator = _Coordinator()

    async def _loads(entry_id: str) -> None:
        hass.config_entries.reloaded.append(entry_id)
        entry.state = ConfigEntryState.LOADED
        coordinator.auth_failed = False
        coordinator.last_update_success = True
        hass.data[DOMAIN][entry_id] = coordinator

    hass.config_entries.async_reload = _loads

    asyncio.run(refresh(hass, connection, _msg()))

    assert hass.config_entries.reloaded == ["entry-1"]
    assert connection.errors == []
    assert connection.results[-1]["status"] == "connected"


def test_refresh_reports_the_reason_when_the_retry_fails_too() -> None:
    """A session that is still dead has to say so rather than look fixed."""
    hass, entry, connection = _setup(reason="TextNow rejected the session (HTTP 401)")

    asyncio.run(refresh(hass, connection, _msg()))

    assert hass.config_entries.reloaded == ["entry-1"]
    assert connection.results[-1]["status"] == "reauth_required"
    assert "401" in connection.results[-1]["last_error"]


def test_refresh_re_arms_an_account_that_was_slowed_down() -> None:
    """The escape hatch from the recovery interval, for the impatient."""
    coordinator = _Coordinator()
    hass, _entry, connection = _setup(
        state=ConfigEntryState.LOADED, coordinator=coordinator
    )

    asyncio.run(refresh(hass, connection, _msg()))

    assert coordinator.rearmed == 1
    assert coordinator.refreshed == 1
    assert hass.config_entries.reloaded == []
    assert connection.results[-1]["status"] == "connected"


def test_refresh_on_an_unknown_account_is_an_error() -> None:
    hass, _entry, connection = _setup()

    asyncio.run(refresh(hass, connection, _msg("nope")))

    assert connection.errors[0][0] == "not_found"


# ------------------------------------------------------------- start_reauth


def test_the_sign_in_button_opens_a_prompt() -> None:
    hass, _entry, connection = _setup()

    asyncio.run(start_reauth(hass, connection, _msg()))

    assert connection.errors == []
    assert connection.results[-1]["started"] is True
    assert len(hass.flow.flows) == 1


def test_the_sign_in_button_points_at_a_prompt_already_waiting() -> None:
    """Two identical forms would be worse than one, but say which one it is."""
    hass, _entry, connection = _setup()
    hass.flow.add_flow(flow_id="already-open")

    asyncio.run(start_reauth(hass, connection, _msg()))

    assert connection.results[-1] == {
        "success": True,
        "started": False,
        "flow_id": "already-open",
    }
    assert len(hass.flow.flows) == 1


def test_the_sign_in_button_clears_wreckage_blocking_it() -> None:
    """The reported bug: the button was correct to press and did nothing.

    A flow that never reached a step is invisible to the user and to the
    integrations page, but it was counted as a prompt already open, so the
    button declined to start the one the user was asking for -- and Home
    Assistant's own de-duplication would have refused too.
    """
    hass, _entry, connection = _setup()
    hass.flow.add_flow(flow_id="orphan", step_id=None)

    asyncio.run(start_reauth(hass, connection, _msg()))

    assert "orphan" in hass.flow.aborted
    assert connection.errors == []
    assert connection.results[-1]["started"] is True
    visible = [flow for flow in hass.flow.flows if "step_id" in flow]
    assert len(visible) == 1


def test_the_sign_in_button_says_so_when_no_prompt_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silence is the one outcome that is not allowed."""
    monkeypatch.setattr(websocket, "REAUTH_WAIT_ATTEMPTS", 2)
    hass, entry, connection = _setup()
    entry.async_start_reauth = lambda hass: None

    asyncio.run(start_reauth(hass, connection, _msg()))

    assert connection.results == []
    assert connection.errors[0][0] == "reauth_not_started"
    assert "Devices & services" in connection.errors[0][1]


def test_the_sign_in_button_on_an_unknown_account_is_an_error() -> None:
    hass, _entry, connection = _setup()

    asyncio.run(start_reauth(hass, connection, _msg("nope")))

    assert connection.errors[0][0] == "not_found"
