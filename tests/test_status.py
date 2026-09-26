"""The status the panel shows for an account.

One word has to cover every state Home Assistant can leave an entry in, and
it has to be right when the entry never loaded, which is exactly what an
expired session does.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.textnow.websocket import _entry_status


def _entry(state: ConfigEntryState, *, disabled: bool = False, reauth: bool = False):
    return SimpleNamespace(
        state=state,
        disabled_by="user" if disabled else None,
        async_get_active_flows=lambda hass, sources: (["flow"] if reauth else []),
    )


def _coordinator(*, auth_failed: bool = False, success: bool = True):
    return SimpleNamespace(auth_failed=auth_failed, last_update_success=success)


def test_a_working_account_is_connected() -> None:
    entry = _entry(ConfigEntryState.LOADED)
    assert _entry_status(None, entry, _coordinator()) == "connected"


def test_an_expired_session_asks_for_a_new_sign_in() -> None:
    """The entry never loads, so there is no coordinator to ask."""
    entry = _entry(ConfigEntryState.SETUP_ERROR)
    assert _entry_status(None, entry, None) == "reauth_required"


def test_a_reauth_already_waiting_asks_for_a_new_sign_in() -> None:
    """A retrying entry with a reauth open is a sign-in problem, not a network one."""
    entry = _entry(ConfigEntryState.SETUP_RETRY, reauth=True)
    assert _entry_status(None, entry, None) == "reauth_required"


def test_a_session_rejected_after_loading_asks_for_a_new_sign_in() -> None:
    entry = _entry(ConfigEntryState.LOADED)
    coordinator = _coordinator(auth_failed=True, success=False)
    assert _entry_status(None, entry, coordinator) == "reauth_required"


@pytest.mark.parametrize(
    ("state", "coordinator"),
    [
        (ConfigEntryState.SETUP_RETRY, None),
        (ConfigEntryState.LOADED, _coordinator(success=False)),
    ],
)
def test_a_network_problem_reads_as_offline(state, coordinator) -> None:
    assert _entry_status(None, _entry(state), coordinator) == "offline"


def test_a_switched_off_account_is_not_running() -> None:
    entry = _entry(ConfigEntryState.NOT_LOADED, disabled=True)
    assert _entry_status(None, entry, None) == "disabled"
