"""End to end check of the session handling against a local fake TextNow.

The fake rotates its session cookie the way an Express session does: every
answer carries a new connect.sid and XSRF-TOKEN scoped to Domain=.textnow.com,
and replaying an old value is rejected with 401. All values are made up.
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import pytest
from aiohttp import web

from custom_components.textnow.coordinator import (
    TextNowAuthError,
    TextNowDataUpdateCoordinator,
    async_api_request,
    build_headers,
)


class _Client(TextNowDataUpdateCoordinator):
    """The coordinator's cookie handling without Home Assistant behind it."""

    def __init__(self, cookies: dict[str, str]) -> None:
        self._cookies = dict(cookies)
        self.saved: list[dict[str, str]] = []

    def _async_persist_cookies(self) -> None:
        self.saved.append(dict(self._cookies))


class _FakeTextNow:
    """Accepts one session cookie at a time and rotates it on every call."""

    def __init__(self) -> None:
        self.session_id = "session-1"
        self.csrf = "token-1"
        self.rotations = 0
        self.rejected = 0
        self.received: list[dict[str, Any]] = []

    def _rotate(self, response: web.StreamResponse) -> None:
        self.rotations += 1
        self.session_id = f"session-{self.rotations + 1}"
        self.csrf = f"token-{self.rotations + 1}"
        response.set_cookie(
            "connect.sid", self.session_id, domain=".textnow.com", path="/"
        )
        response.set_cookie("XSRF-TOKEN", self.csrf, domain=".textnow.com", path="/")

    def _check(self, request: web.Request) -> None:
        if request.cookies.get("connect.sid") != self.session_id:
            self.rejected += 1
            raise web.HTTPUnauthorized(
                text='{"error_code":"AUTHENTICATION_FAILED"}',
                content_type="application/json",
            )
        if request.headers.get("X-CSRF-Token") != self.csrf:
            self.rejected += 1
            raise web.HTTPForbidden(
                text='{"error_code":"CSRF"}', content_type="application/json"
            )

    async def get_messages(self, request: web.Request) -> web.Response:
        self._check(request)
        self.received.append({"method": "GET", "headers": dict(request.headers)})
        response = web.json_response({"messages": [{"id": 1}]})
        self._rotate(response)
        return response

    async def post_message(self, request: web.Request) -> web.Response:
        self._check(request)
        self.received.append({"method": "POST", "body": await request.json()})
        response = web.json_response({"id": 42})
        self._rotate(response)
        return response


async def _serve(fake: _FakeTextNow) -> tuple[str, web.AppRunner]:
    app = web.Application()
    app.router.add_get("/api/users/{user}/messages", fake.get_messages)
    app.router.add_post("/api/users/{user}/messages", fake.post_message)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    return f"http://127.0.0.1:{port}", runner


async def _poll(client: _Client, session: aiohttp.ClientSession, base: str) -> Any:
    return await async_api_request(
        session,
        "GET",
        f"{base}/api/users/example/messages",
        headers_factory=lambda: build_headers(client._cookies),
        cookies_factory=lambda: client._cookies,
        cookie_sink=client._async_absorb_cookies,
        attempts=1,
    )


def test_a_rotating_session_survives_repeated_polls() -> None:
    """Replaying the cookie the session started with is what loses it."""

    async def scenario() -> None:
        fake = _FakeTextNow()
        base, runner = await _serve(fake)
        client = _Client({"connect.sid": "session-1", "XSRF-TOKEN": "token-1"})
        session = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())

        try:
            for _ in range(5):
                assert await _poll(client, session, base) == {
                    "messages": [{"id": 1}]
                }

            assert fake.rejected == 0
            assert fake.rotations == 5
            assert client._cookies["connect.sid"] == "session-6"
            # Each rotation is written back so a restart is still signed in
            assert len(client.saved) == 5
        finally:
            await session.close()
            await runner.cleanup()

    asyncio.run(scenario())


def test_sending_uses_the_rotated_session() -> None:
    """Sending right after a poll must not reuse the retired cookie."""

    async def scenario() -> None:
        fake = _FakeTextNow()
        base, runner = await _serve(fake)
        client = _Client({"connect.sid": "session-1", "XSRF-TOKEN": "token-1"})
        session = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())

        try:
            await _poll(client, session, base)
            await async_api_request(
                session,
                "POST",
                f"{base}/api/users/example/messages",
                headers_factory=lambda: build_headers(client._cookies),
                cookies_factory=lambda: client._cookies,
                cookie_sink=client._async_absorb_cookies,
                json_data={"message": "hello", "contact_value": "+15555550100"},
                attempts=1,
            )

            assert fake.rejected == 0
            assert fake.received[-1]["body"]["message"] == "hello"
        finally:
            await session.close()
            await runner.cleanup()

    asyncio.run(scenario())


def test_a_stale_cookie_is_reported_as_an_auth_failure() -> None:
    """The 401 the live instance logged must reach Home Assistant."""

    async def scenario() -> None:
        fake = _FakeTextNow()
        base, runner = await _serve(fake)
        client = _Client({"connect.sid": "expired", "XSRF-TOKEN": "token-1"})
        session = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())

        try:
            with pytest.raises(TextNowAuthError):
                await _poll(client, session, base)
            assert fake.rejected == 1
        finally:
            await session.close()
            await runner.cleanup()

    asyncio.run(scenario())


def test_the_browser_fingerprint_is_sent_on_every_call() -> None:
    """PerimeterX scores requests that claim Chrome but omit its headers."""

    async def scenario() -> None:
        fake = _FakeTextNow()
        base, runner = await _serve(fake)
        client = _Client({"connect.sid": "session-1", "XSRF-TOKEN": "token-1"})
        session = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())

        try:
            await _poll(client, session, base)
            headers = fake.received[0]["headers"]

            assert "Chrome/" in headers["User-Agent"]
            assert headers["Accept-Language"].startswith("en-US")
            assert headers["sec-ch-ua-mobile"] == "?0"
            assert headers["Sec-Fetch-Site"] == "same-origin"
            assert headers["Referer"].endswith("/messaging")
            assert headers["Origin"] == "https://www.textnow.com"
        finally:
            await session.close()
            await runner.cleanup()

    asyncio.run(scenario())
