"""The keep-alive that stops TextNow reclaiming an idle number.

TextNow hands a number that nobody uses back to the pool, which would take
the user's number and break every automation pointed at it. All numbers here
are in the 555 range reserved for fiction.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.textnow.const import (
    CONF_KEEPALIVE_DAYS,
    CONF_KEEPALIVE_MESSAGE,
    CONF_KEEPALIVE_PHONE,
    DEFAULT_KEEPALIVE_DAYS,
    DEFAULT_KEEPALIVE_MESSAGE,
    MAX_KEEPALIVE_DAYS,
    MIN_KEEPALIVE_DAYS,
)
from custom_components.textnow.coordinator import TextNowDataUpdateCoordinator

SAFE_NUMBER = "+15555550100"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _Storage:
    """The parts of the store the keep-alive touches."""

    def __init__(self, last_outbound: str | None = None) -> None:
        self.last_outbound = last_outbound
        self.writes = 0

    async def async_get_last_outbound(self) -> str | None:
        return self.last_outbound

    async def async_set_last_outbound(self, when: str) -> None:
        self.last_outbound = when
        self.writes += 1


class _Account(TextNowDataUpdateCoordinator):
    """The coordinator's keep-alive logic without Home Assistant behind it."""

    def __init__(self, *, stored: str | None = None, **config: Any) -> None:
        self._config = {CONF_KEEPALIVE_PHONE: SAFE_NUMBER, **config}
        self._last_outbound = None
        self._last_outbound_read = False
        self._keepalive_checked = None
        self._keepalive_task = None
        self.storage = _Storage(stored)
        self.sent: list[tuple[str, str]] = []
        self.fail_with: Exception | None = None

    async def send_message(self, phone: str, message: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append((phone, message))
        await self.async_note_outbound_use()


def _days_ago(days: float) -> str:
    return (dt_util.utcnow() - timedelta(days=days)).isoformat()


def test_an_idle_number_gets_a_message() -> None:
    account = _Account(stored=_days_ago(6))
    assert _run(account.async_run_keepalive()) is True
    assert account.sent == [(SAFE_NUMBER, DEFAULT_KEEPALIVE_MESSAGE)]


def test_a_number_used_yesterday_is_left_alone() -> None:
    account = _Account(stored=_days_ago(1))
    assert _run(account.async_run_keepalive()) is False
    assert account.sent == []


def test_leaving_the_number_empty_turns_the_keep_alive_off() -> None:
    account = _Account(stored=_days_ago(90), **{CONF_KEEPALIVE_PHONE: ""})
    assert _run(account.async_run_keepalive(force=True)) is False
    assert account.sent == []


def test_the_first_run_sends_once_to_start_the_clock() -> None:
    """Nothing recorded means the idle time is unknown, so assume the worst."""
    account = _Account(stored=None)
    assert _run(account.async_run_keepalive()) is True
    assert account.storage.last_outbound is not None


def test_anything_the_user_sends_resets_the_clock() -> None:
    account = _Account(stored=_days_ago(6))

    async def scenario() -> None:
        await account.send_message("+15555550199", "dinner is ready")
        account.sent.clear()
        assert await account.async_run_keepalive() is False

    _run(scenario())
    assert account.sent == []


def test_a_second_check_within_the_hour_does_nothing() -> None:
    """Polling runs every 30 seconds; the keep-alive must not ride along."""
    account = _Account(stored=_days_ago(6))

    async def scenario() -> None:
        assert await account.async_run_keepalive() is True
        # Pretend the message never landed, so only the hourly guard can
        # hold the second attempt back.
        account._last_outbound = dt_util.utcnow() - timedelta(days=6)
        assert await account.async_run_keepalive() is False

    _run(scenario())
    assert len(account.sent) == 1


def test_sending_now_ignores_both_the_timer_and_the_hourly_guard() -> None:
    account = _Account(stored=_days_ago(1))

    async def scenario() -> None:
        assert await account.async_run_keepalive(force=True) is True
        assert await account.async_run_keepalive(force=True) is True

    _run(scenario())
    assert len(account.sent) == 2


def test_a_failed_send_is_reported_and_retried_later(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A dead session already shows up as a reauth prompt; do not pile on."""
    account = _Account(stored=_days_ago(6))
    account.fail_with = HomeAssistantError("session expired")

    async def scenario() -> None:
        assert await account.async_run_keepalive() is False
        assert "keep-alive" in caplog.text
        account.fail_with = None
        assert await account.async_run_keepalive(force=True) is True

    _run(scenario())


def test_the_due_date_follows_the_configured_gap() -> None:
    account = _Account(stored=_days_ago(0), **{CONF_KEEPALIVE_DAYS: 3})
    _run(account.async_run_keepalive(force=True))

    due = account.keepalive_due_at
    assert due is not None
    assert abs((due - account.last_outbound) - timedelta(days=3)) < timedelta(seconds=1)


def test_nothing_is_due_while_the_keep_alive_is_off() -> None:
    account = _Account(**{CONF_KEEPALIVE_PHONE: ""})
    assert account.keepalive_due_at is None


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, DEFAULT_KEEPALIVE_DAYS),
        ("", DEFAULT_KEEPALIVE_DAYS),
        ("not a number", DEFAULT_KEEPALIVE_DAYS),
        (0, DEFAULT_KEEPALIVE_DAYS),
        (-4, MIN_KEEPALIVE_DAYS),
        (365, MAX_KEEPALIVE_DAYS),
        (7, 7),
        ("7", 7),
    ],
)
def test_an_unusable_gap_falls_back_to_something_sensible(
    configured: Any, expected: int
) -> None:
    account = _Account(**{CONF_KEEPALIVE_DAYS: configured})
    assert account.keepalive_days == expected


@pytest.mark.parametrize("configured", [None, "", "   "])
def test_an_empty_message_falls_back_to_the_default(configured: Any) -> None:
    account = _Account(**{CONF_KEEPALIVE_MESSAGE: configured})
    assert account.keepalive_message == DEFAULT_KEEPALIVE_MESSAGE


def test_a_custom_message_is_used_as_written() -> None:
    account = _Account(
        stored=_days_ago(6), **{CONF_KEEPALIVE_MESSAGE: "  still here  "}
    )
    _run(account.async_run_keepalive())
    assert account.sent == [(SAFE_NUMBER, "still here")]
