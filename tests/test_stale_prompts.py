"""Sign-in prompts must not outlive the problem they were asking about.

Home Assistant drops a pending reauth prompt when an entry sets up
successfully, but nothing drops one when a later poll or send succeeds --
which is how this integration actually recovers. A prompt left standing was
enough to keep the panel demanding a sign-in while messages were going out
normally, and enough to make the panel's own button refuse to open a new one.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.textnow.coordinator import (
    TextNowAuthError,
    TextNowDataUpdateCoordinator,
)
from custom_components.textnow.reauth import (
    async_clear_reauth_flows,
    async_visible_reauth_flows,
)
from fakes import FakeHass


class _Storage:
    def __init__(self) -> None:
        self.last_outbound: str | None = None

    async def async_get_last_outbound(self) -> str | None:
        return self.last_outbound

    async def async_set_last_outbound(self, when: str) -> None:
        self.last_outbound = when


class _Account(TextNowDataUpdateCoordinator):
    """The recovery paths without Home Assistant behind them."""

    def __init__(self, failure: Exception | None = None) -> None:
        self.auth_failed = False
        self.last_success = None
        self._config: dict[str, Any] = {"polling_interval": 30}
        self._cookies: dict[str, str] = {}
        self._failures = 0
        self._failure = failure
        self._last_outbound = None
        self._last_outbound_read = False
        self._keepalive_checked = None
        self._keepalive_task = None
        self.update_interval = None
        self.storage = _Storage()
        self.hass = FakeHass()
        self.entry = self.hass.make_entry()

    async def _poll_unread_messages(self) -> None:
        if self._failure is not None:
            raise self._failure

    async def _cleanup_expired_pending(self) -> None:
        return None

    def _async_report_auth_problem(self, err: Exception) -> None:
        return None

    def _async_persist_cookies(self, force: bool = False) -> None:
        return None


def test_a_successful_poll_clears_a_prompt_left_over() -> None:
    account = _Account()
    account.hass.flow.add_flow(flow_id="leftover")

    asyncio.run(account._async_update_data())

    assert account.hass.flow.flows == []
    assert async_visible_reauth_flows(account.hass, account.entry) == []


def test_a_successful_poll_clears_invisible_wreckage_too() -> None:
    """A flow with no step is the one that jams the sign-in button."""
    account = _Account()
    account.hass.flow.add_flow(flow_id="orphan", step_id=None)

    asyncio.run(account._async_update_data())

    assert account.hass.flow.aborted == ["orphan"]


def test_a_failing_poll_leaves_the_prompt_alone() -> None:
    """The prompt is still the right thing to be asking for."""
    account = _Account(TextNowAuthError("expired"))
    account.hass.flow.add_flow(flow_id="wanted")

    with pytest.raises(ConfigEntryAuthFailed):
        asyncio.run(account._async_update_data())

    assert [flow["flow_id"] for flow in account.hass.flow.flows] == ["wanted"]


def test_a_message_textnow_accepted_clears_the_prompt() -> None:
    """A send proves the session works more directly than a poll does."""
    account = _Account()
    account.auth_failed = True
    account.hass.flow.add_flow(flow_id="leftover")

    asyncio.run(account.async_note_outbound_use())

    assert account.auth_failed is False
    assert account.hass.flow.flows == []


def test_clearing_a_prompt_that_has_already_gone_is_not_an_error() -> None:
    """Two recovery paths can race, and a finished flow is the goal anyway."""
    hass = FakeHass()
    entry = hass.make_entry()
    flow = hass.flow.add_flow(flow_id="racing")

    # Listed, then finished by something else before the abort lands
    original = hass.flow.async_abort

    def _abort(flow_id: str) -> None:
        hass.flow.flows.remove(flow)
        original(flow_id)

    hass.flow.async_abort = _abort

    assert async_clear_reauth_flows(hass, entry) == 0
    assert hass.flow.flows == []
