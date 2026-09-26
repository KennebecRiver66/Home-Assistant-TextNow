"""The status the panel shows for an account.

One word has to cover every state Home Assistant can leave an entry in, and
it has to be right when the entry never loaded, which is exactly what an
expired session does.

The entries here come from `fakes.py` so they behave the way Home Assistant's
really do. An earlier version of this file stubbed
`async_get_active_flows` as a function returning a list, which is falsy when
empty. The real one returns a generator, which never is -- so the suite passed
while the panel reported "sign-in needed" for every healthy account.
"""
from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from types import SimpleNamespace

from custom_components.textnow.websocket import _entry_status
from fakes import FakeHass


def _setup(
    state: ConfigEntryState,
    *,
    disabled: bool = False,
    reauth: bool = False,
    orphan_flow: bool = False,
):
    hass = FakeHass()
    entry = hass.make_entry(state=state)
    if disabled:
        entry.disabled_by = "user"
    if reauth:
        hass.flow.add_flow(flow_id="visible")
    if orphan_flow:
        hass.flow.add_flow(flow_id="orphan", step_id=None)
    return hass, entry


def _coordinator(*, auth_failed: bool = False, success: bool = True):
    return SimpleNamespace(auth_failed=auth_failed, last_update_success=success)


def test_a_working_account_is_connected() -> None:
    hass, entry = _setup(ConfigEntryState.LOADED)
    assert _entry_status(hass, entry, _coordinator()) == "connected"


def test_an_expired_session_asks_for_a_new_sign_in() -> None:
    """The entry never loads, so there is no coordinator to ask."""
    hass, entry = _setup(ConfigEntryState.SETUP_ERROR)
    assert _entry_status(hass, entry, None) == "reauth_required"


def test_a_reauth_already_waiting_asks_for_a_new_sign_in() -> None:
    """A retrying entry with a prompt open is a sign-in problem, not a network one."""
    hass, entry = _setup(ConfigEntryState.SETUP_RETRY, reauth=True)
    assert _entry_status(hass, entry, None) == "reauth_required"


def test_a_session_rejected_after_loading_asks_for_a_new_sign_in() -> None:
    hass, entry = _setup(ConfigEntryState.LOADED)
    coordinator = _coordinator(auth_failed=True, success=False)
    assert _entry_status(hass, entry, coordinator) == "reauth_required"


def test_a_successful_poll_outranks_an_open_sign_in_prompt() -> None:
    """The reported bug: the banner would not go away while sending worked.

    A prompt left open is a piece of interface, not evidence about the
    session. A poll that just succeeded is evidence, and it wins.
    """
    hass, entry = _setup(ConfigEntryState.LOADED, reauth=True)
    assert _entry_status(hass, entry, _coordinator()) == "connected"


def test_an_invisible_flow_is_never_mistaken_for_a_prompt() -> None:
    """A flow with no step cannot be answered or dismissed by anyone.

    Counting one as a request to sign in produced a banner with no form
    behind it, and the integrations page never showed anything at all.
    """
    hass, entry = _setup(ConfigEntryState.SETUP_RETRY, orphan_flow=True)
    assert _entry_status(hass, entry, None) == "offline"


def test_the_empty_generator_is_not_read_as_a_waiting_prompt() -> None:
    """async_get_active_flows is truthy even when it yields nothing.

    This is the trap the whole bug rested on, so it is worth asserting
    directly rather than only through the statuses above.
    """
    hass, entry = _setup(ConfigEntryState.SETUP_RETRY)
    assert bool(entry.async_get_active_flows(hass, {"reauth"})) is True
    assert _entry_status(hass, entry, None) == "offline"


@pytest.mark.parametrize(
    ("state", "coordinator"),
    [
        (ConfigEntryState.SETUP_RETRY, None),
        (ConfigEntryState.LOADED, _coordinator(success=False)),
    ],
)
def test_a_network_problem_reads_as_offline(state, coordinator) -> None:
    hass, entry = _setup(state)
    assert _entry_status(hass, entry, coordinator) == "offline"


def test_a_switched_off_account_is_not_running() -> None:
    hass, entry = _setup(ConfigEntryState.NOT_LOADED, disabled=True)
    assert _entry_status(hass, entry, None) == "disabled"
