"""Tests for when rotated cookies reach the config entry.

TextNow rotates cookies on nearly every call, so writing the config entry
every time would hammer the disk. Throttling that write is only safe if the
saved set can never end up older than the session it belongs to: a saved
login cookie paired with a token from a different rotation reads server side
as a forged request. All values here are made up.
"""
from __future__ import annotations

import asyncio
from http.cookies import SimpleCookie
from typing import Any

from homeassistant.util import dt as dt_util

from custom_components.textnow.const import CONF_COOKIES
from custom_components.textnow.coordinator import (
    COOKIE_PERSIST_INTERVAL,
    TextNowDataUpdateCoordinator,
)


class _FakeEntry:
    """A config entry that records what gets written to it."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.entry_id = "entry-1"
        self.data = data


class _FakeConfigEntries:
    def __init__(self, entry: _FakeEntry) -> None:
        self._entry: _FakeEntry | None = entry
        self.writes: list[dict[str, Any]] = []

    def async_update_entry(self, entry: _FakeEntry, *, data: dict[str, Any]) -> None:
        entry.data = data
        self.writes.append(data)

    def async_get_entry(self, entry_id: str) -> _FakeEntry | None:
        return self._entry


class _FakeHass:
    def __init__(self, entry: _FakeEntry) -> None:
        self.config_entries = _FakeConfigEntries(entry)


class _Coordinator(TextNowDataUpdateCoordinator):
    """The cookie persistence logic without Home Assistant behind it."""

    def __init__(self, stored: dict[str, Any]) -> None:
        self.entry = _FakeEntry(dict(stored))
        self.hass = _FakeHass(self.entry)
        self._cookies = {
            name: str(value) for name, value in (stored.get(CONF_COOKIES) or {}).items()
        }
        self._last_cookie_write: Any = None
        self._cookies_unsaved = False
        self.session = None
        # Enough of DataUpdateCoordinator for async_shutdown to run
        self._shutdown_requested = False
        self._unsub_refresh = None
        self._unsub_shutdown = None
        self._debounced_refresh = _NoDebouncer()

    @property
    def writes(self) -> list[dict[str, Any]]:
        return self.hass.config_entries.writes


class _NoDebouncer:
    def async_shutdown(self) -> None:
        return None


def _stored(**cookies: str) -> dict[str, Any]:
    return {
        CONF_COOKIES: dict(cookies),
        "connect_sid": cookies.get("connect.sid", ""),
        "csrf": cookies.get("_csrf", ""),
        "xsrf_token": cookies.get("XSRF-TOKEN", ""),
    }


def _rotate(**cookies: str) -> SimpleCookie:
    jar = SimpleCookie()
    for name, value in cookies.items():
        jar[name] = value
        jar[name]["domain"] = ".textnow.com"
    return jar


def test_a_rotated_token_is_saved_immediately() -> None:
    """A token that outlives its session in storage is worse than no token."""
    coordinator = _Coordinator(
        _stored(**{"connect.sid": "sid-1", "XSRF-TOKEN": "token-1"})
    )
    # A write happened moments ago, so the throttle window is wide open
    coordinator._last_cookie_write = dt_util.utcnow()

    coordinator._async_absorb_cookies(_rotate(**{"XSRF-TOKEN": "token-2"}))

    assert coordinator.writes, "the rotated CSRF token was held back"
    assert coordinator.writes[-1]["xsrf_token"] == "token-2"
    assert coordinator._cookies_unsaved is False


def test_bot_protection_noise_is_throttled() -> None:
    """The cookies that rotate every call must not write the entry every call."""
    coordinator = _Coordinator(_stored(**{"connect.sid": "sid-1"}))
    coordinator._last_cookie_write = dt_util.utcnow()

    coordinator._async_absorb_cookies(_rotate(_pxhd="noise-2"))

    assert coordinator.writes == []
    assert coordinator._cookies_unsaved is True


def test_held_back_cookies_are_flushed_when_the_entry_unloads() -> None:
    """A restart inside the throttle window must not resurrect a stale set.

    Without the flush, the entry would still hold the cookies from up to
    fifteen minutes earlier, and the next start would replay a set the session
    had already moved on from.
    """
    coordinator = _Coordinator(_stored(**{"connect.sid": "sid-1"}))
    coordinator._last_cookie_write = dt_util.utcnow()
    coordinator._async_absorb_cookies(_rotate(_pxhd="noise-2"))
    assert coordinator.writes == []

    asyncio.run(coordinator.async_shutdown())

    assert coordinator.writes[-1][CONF_COOKIES]["_pxhd"] == "noise-2"
    assert coordinator._cookies_unsaved is False


def test_nothing_is_written_on_unload_when_nothing_is_pending() -> None:
    """Unloading a quiet account must not touch the config entry."""
    coordinator = _Coordinator(_stored(**{"connect.sid": "sid-1"}))

    asyncio.run(coordinator.async_shutdown())

    assert coordinator.writes == []


def test_the_throttle_reopens_once_the_window_passes() -> None:
    """Noise is not dropped forever, just batched."""
    coordinator = _Coordinator(_stored(**{"connect.sid": "sid-1"}))
    coordinator._last_cookie_write = dt_util.utcnow() - COOKIE_PERSIST_INTERVAL

    coordinator._async_absorb_cookies(_rotate(_pxhd="noise-2"))

    assert coordinator.writes[-1][CONF_COOKIES]["_pxhd"] == "noise-2"
