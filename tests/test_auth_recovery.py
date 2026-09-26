"""Recovering from an expired session without restarting Home Assistant.

The reported lockup: a poll got a 401, the coordinator set auth_failed and
cleared update_interval, and since auth_failed is only ever cleared by a
poll completing, removing the interval removed the only thing that could
clear it. The account sat in "needs to reconnect" with its send controls
disabled until Home Assistant restarted.

These run the real coordinator against a local fake TextNow. All values
are made up.
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from homeassistant.exceptions import ConfigEntryAuthFailed

from fakes import FakeHass

from custom_components.textnow.const import AUTH_RECOVERY_INTERVAL
from custom_components.textnow.coordinator import (
    TextNowDataUpdateCoordinator,
    async_api_request,
    build_headers,
)


class _FakeTextNow:
    """Accepts one session cookie and can be made to reject it."""

    def __init__(self) -> None:
        self.valid = "session-good"
        self.calls = 0

    async def get_messages(self, request: web.Request) -> web.Response:
        self.calls += 1
        cookie = request.cookies.get("connect.sid")
        if cookie != self.valid:
            return web.json_response(
                {"error_code": "AUTHENTICATION_FAILED"}, status=401
            )
        return web.json_response({"messages": []})


async def _serve(fake: _FakeTextNow) -> tuple[str, web.AppRunner]:
    app = web.Application()
    app.router.add_get("/api/users/{user}/messages", fake.get_messages)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return f"http://127.0.0.1:{runner.addresses[0][1]}", runner


class _Account(TextNowDataUpdateCoordinator):
    """The coordinator's polling lifecycle, talking to the fake."""

    def __init__(self, base: str, session: aiohttp.ClientSession) -> None:
        self.auth_failed = False
        self.last_success = None
        self._config: dict[str, Any] = {"polling_interval": 30}
        self._cookies = {"connect.sid": "session-good", "XSRF-TOKEN": "token"}
        self._failures = 0
        self._base = base
        self._session = session
        self.update_interval = None
        self.reauth_prompts = 0
        self.hass = FakeHass()
        self.entry = self.hass.make_entry()

    async def _poll_unread_messages(self) -> None:
        await async_api_request(
            self._session,
            "GET",
            f"{self._base}/api/users/example/messages",
            headers_factory=lambda: build_headers(self._cookies),
            attempts=1,
        )

    async def _cleanup_expired_pending(self) -> None:
        return None

    def _async_report_auth_problem(self, err: Exception) -> None:
        # Home Assistant opens the reauth prompt off the back of the
        # ConfigEntryAuthFailed; this counts how often that would happen.
        self.reauth_prompts += 1

    def _async_clear_auth_problem(self) -> None:
        return None

    def _async_persist_cookies(self) -> None:
        return None


def test_an_expired_session_recovers_on_its_own_once_the_cookie_is_fixed() -> None:
    """The user's acceptance test, end to end against a real 401."""

    async def scenario() -> None:
        fake = _FakeTextNow()
        base, runner = await _serve(fake)
        session = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())
        account = _Account(base, session)

        try:
            await account._async_update_data()
            assert account.auth_failed is False
            assert account.update_interval.total_seconds() == 30

            # TextNow signs the session out.
            fake.valid = "session-rotated"
            with pytest.raises(ConfigEntryAuthFailed):
                await account._async_update_data()

            assert account.auth_failed is True
            assert account.reauth_prompts == 1
            # The bug: this used to be None, and nothing was ever scheduled
            # again, so nothing could ever clear auth_failed.
            assert account.update_interval == AUTH_RECOVERY_INTERVAL

            # While it stays broken, each recovery poll re-offers the prompt
            # rather than leaving a dismissed one gone for good.
            with pytest.raises(ConfigEntryAuthFailed):
                await account._async_update_data()
            assert account.reauth_prompts == 2

            # Reauth writes fresh cookies. No restart, no reload.
            account._cookies["connect.sid"] = "session-rotated"
            await account._async_update_data()

            assert account.auth_failed is False
            assert account.update_interval.total_seconds() == 30
            assert account.last_success is not None
        finally:
            await session.close()
            await runner.cleanup()

    asyncio.run(scenario())


def test_a_dead_session_is_not_polled_at_the_normal_rate() -> None:
    """Recovering must not undo the reason polling was slowed down."""

    async def scenario() -> None:
        fake = _FakeTextNow()
        fake.valid = "nothing-matches-this"
        base, runner = await _serve(fake)
        session = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())
        account = _Account(base, session)

        try:
            for _ in range(3):
                with pytest.raises(ConfigEntryAuthFailed):
                    await account._async_update_data()

            assert account.update_interval == AUTH_RECOVERY_INTERVAL
            # 30 minutes is 48 requests a day rather than 2880.
            assert account.update_interval.total_seconds() >= 900
        finally:
            await session.close()
            await runner.cleanup()

    asyncio.run(scenario())
