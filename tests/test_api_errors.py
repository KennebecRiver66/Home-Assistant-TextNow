"""Tests for how TextNow failures are classified and retried."""
from __future__ import annotations

import asyncio
from http.cookies import SimpleCookie
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.textnow import coordinator as coordinator_module
from custom_components.textnow.const import AUTH_RECOVERY_INTERVAL
from custom_components.textnow.coordinator import (
    TextNowApiError,
    TextNowAuthError,
    TextNowBlockedError,
    TextNowConnectionError,
    TextNowDataUpdateCoordinator,
    TextNowWebAccessError,
    _extract_messages,
    _parse_json_body,
    async_api_request,
)
from custom_components.textnow.storage import _trim_message_ids
from fakes import FakeHass

PERIMETERX_BODY = (
    "<html><head><title>Access to this page has been denied</title>"
    "<script>window._pxAppId</script>PerimeterX</html>"
)

# Copied from a user report, byte for byte. TextNow's API answers a blocked
# call with this rather than PerimeterX's interstitial page, so the markers
# have to survive a shape that carries no HTML and no "denied" anywhere.
PERIMETERX_API_BODY = (
    r'{"result":{"appId":"PXK56WkC4O","jsClientSrc":"\/\/client.perimeterx.net'
    r'\/PXK56WkC4O\/main.min.js","firstPartyEnabled":false,"vid":null,'
    r'"uuid":"3337b540-46a0-11f1-a1be-8ce1146c5c3d","hostUrl":'
    r'"https:\/\/collector-pxk56wkc4o.perimeterx.net","blockScript":'
    r'"https:\/\/captcha.px-cdn.net\/PXK56WkC4O\/captcha.js?a=c\u0026'
    r'u=3337b540-46a0-11f1-a1be-8ce1146c5c3d\u0026v=\u0026m=0",'
    r'"altBlockScript":"https:\/\/captcha.px-cloud.net\/PXK56WkC4O\/captcha.js'
    r'?a=c\u0026u=3337b540-46a0-11f1-a1be-8ce1146c5c3d\u0026v=\u0026m=0",'
    r'"customLogo":"https:\/\/textnow-static.s3.amazonaws.com\/TextNowLogo.jpg"'
    r'},"error_code":"PERIMETERX_RESPONSE"}'
)


class _FakeResponse:
    """Minimal stand-in for an aiohttp response."""

    def __init__(
        self, status: int, body: str, set_cookies: dict[str, str] | None = None
    ) -> None:
        self.status = status
        self._body = body
        self.cookies = SimpleCookie()
        for name, value in (set_cookies or {}).items():
            self.cookies[name] = value

    async def text(self) -> str:
        return self._body

    async def read(self) -> bytes:
        return self._body.encode()

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None


class _FakeSession:
    """Returns queued responses or raises queued errors."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append({"method": method, "url": url, **kwargs})
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _headers() -> dict[str, str]:
    return {"X-CSRF-Token": "fake"}


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the retry tests instant."""
    monkeypatch.setattr("custom_components.textnow.coordinator.RETRY_DELAY", 0)


def test_unauthorized_is_an_auth_error() -> None:
    """A 401 means the cookies expired, not a transient glitch."""
    session = _FakeSession([_FakeResponse(401, '{"error_code":"AUTHENTICATION_FAILED"}')])

    with pytest.raises(TextNowAuthError):
        _run(
            async_api_request(
                session, "GET", "https://example.invalid", headers_factory=_headers
            )
        )

    # No retries: replaying a rejected session is what gets an IP blocked
    assert len(session.calls) == 1


def test_bot_protection_is_reported_separately() -> None:
    """A PerimeterX 403 needs different advice than an expired session."""
    session = _FakeSession([_FakeResponse(403, PERIMETERX_BODY)])

    with pytest.raises(TextNowBlockedError) as err:
        _run(
            async_api_request(
                session, "GET", "https://example.invalid", headers_factory=_headers
            )
        )

    assert "bot protection" in str(err.value)
    assert err.value.issue_key == "bot_blocked"


def test_plain_forbidden_is_an_auth_error() -> None:
    """A 403 without bot markers still means new cookies are needed."""
    forbidden = '{"error_code":"FORBIDDEN"}'
    session = _FakeSession([_FakeResponse(403, forbidden) for _ in range(3)])

    with pytest.raises(TextNowAuthError) as err:
        _run(
            async_api_request(
                session, "GET", "https://example.invalid", headers_factory=_headers
            )
        )

    assert not isinstance(err.value, TextNowBlockedError)


def test_a_csrf_mismatch_is_retried_with_the_refreshed_token() -> None:
    """A lone 403 is usually the token and the cookie disagreeing.

    TextNow sends the replacement token on the very reply that refuses the
    request, so retrying once with it settles the call. Demanding a whole new
    sign-in for that would be sending the user to Chrome over nothing.
    """
    tokens: list[str] = []

    def _headers_with_token() -> dict[str, str]:
        tokens.append(f"token-{len(tokens)}")
        return {"X-CSRF-Token": tokens[-1]}

    session = _FakeSession(
        [
            _FakeResponse(
                403,
                '{"error_code":"FORBIDDEN"}',
                set_cookies={"XSRF-TOKEN": "refreshed"},
            ),
            _FakeResponse(200, '{"messages":[]}'),
        ]
    )
    rotated: list[str] = []

    result = _run(
        async_api_request(
            session,
            "GET",
            "https://example.invalid",
            headers_factory=_headers_with_token,
            cookie_sink=lambda jar: rotated.append(jar["XSRF-TOKEN"].value),
        )
    )

    assert result == {"messages": []}
    assert len(session.calls) == 2
    # The refreshed token reached the caller before the second attempt built
    # its headers, which is the whole point of retrying rather than failing.
    assert rotated == ["refreshed"]
    assert tokens == ["token-0", "token-1"]


def test_bot_protection_is_never_retried() -> None:
    """PerimeterX will not change its mind, and hammering it makes it worse."""
    session = _FakeSession([_FakeResponse(403, PERIMETERX_BODY)])

    with pytest.raises(TextNowBlockedError):
        _run(
            async_api_request(
                session, "GET", "https://example.invalid", headers_factory=_headers
            )
        )

    assert len(session.calls) == 1


def test_the_reported_perimeterx_payload_is_read_as_a_block() -> None:
    """The JSON PerimeterX body from the wild, not the interstitial page.

    A send refused this way used to be the thing users reported as "failed to
    send message" with a wall of JSON attached, so it is worth pinning the
    real payload rather than a paraphrase of it.
    """
    session = _FakeSession([_FakeResponse(403, PERIMETERX_API_BODY)])

    with pytest.raises(TextNowBlockedError) as err:
        _run(
            async_api_request(
                session,
                "POST",
                "https://www.textnow.com/api/users/someone/messages",
                headers_factory=_headers,
                json_data={"message": "hello"},
            )
        )

    assert "bot protection" in str(err.value)
    assert err.value.issue_key == "bot_blocked"
    # Not the wait a brand new account is put through, which needs the
    # opposite advice: sit still rather than fetch fresh cookies.
    assert not isinstance(err.value, TextNowWebAccessError)
    # And not a plain API error either, or nothing would ask for a sign-in.
    assert isinstance(err.value, TextNowAuthError)
    assert len(session.calls) == 1


def test_a_refusal_keeps_textnows_own_words_for_a_bug_report(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The advice replaces the payload in the error, so debug has to keep it."""
    session = _FakeSession([_FakeResponse(403, PERIMETERX_API_BODY)])

    with caplog.at_level("DEBUG", logger="custom_components.textnow.coordinator"):
        with pytest.raises(TextNowBlockedError):
            _run(
                async_api_request(
                    session, "POST", "https://example.invalid", headers_factory=_headers
                )
            )

    assert "PERIMETERX_RESPONSE" in caplog.text


def test_upload_host_rejection_is_not_blamed_on_the_session() -> None:
    """A stale pre-signed upload URL must not trigger a reauth prompt."""
    session = _FakeSession([_FakeResponse(403, "<Error>AccessDenied</Error>")])

    with pytest.raises(TextNowApiError) as err:
        _run(
            async_api_request(
                session,
                "PUT",
                "https://uploads.example.invalid/object",
                headers_factory=_headers,
                parse_json=False,
                check_auth=False,
            )
        )

    assert not isinstance(err.value, TextNowAuthError)


def test_transient_failures_are_retried() -> None:
    """A 503 and a dropped connection are worth another attempt."""
    session = _FakeSession(
        [
            _FakeResponse(503, "busy"),
            aiohttp.ClientConnectionError("reset"),
            _FakeResponse(200, '{"messages": []}'),
        ]
    )

    result = _run(
        async_api_request(
            session, "GET", "https://example.invalid", headers_factory=_headers
        )
    )

    assert result == {"messages": []}
    assert len(session.calls) == 3


def test_repeated_failures_become_a_connection_error() -> None:
    """Retries stop and report the last error."""
    session = _FakeSession([_FakeResponse(500, "boom")] * 3)

    with pytest.raises(TextNowConnectionError) as err:
        _run(
            async_api_request(
                session, "GET", "https://example.invalid", headers_factory=_headers
            )
        )

    assert "HTTP 500" in str(err.value)
    assert len(session.calls) == 3


def test_timeout_is_a_connection_error() -> None:
    """A stuck request is transient, not an auth problem."""
    session = _FakeSession([asyncio.TimeoutError()] * 3)

    with pytest.raises(TextNowConnectionError):
        _run(
            async_api_request(
                session, "GET", "https://example.invalid", headers_factory=_headers
            )
        )


def test_headers_are_rebuilt_for_every_attempt() -> None:
    """A rotated CSRF token has to reach the retry."""
    tokens = iter(["first", "second"])
    session = _FakeSession([_FakeResponse(503, ""), _FakeResponse(200, "{}")])

    _run(
        async_api_request(
            session,
            "GET",
            "https://example.invalid",
            headers_factory=lambda: {"X-CSRF-Token": next(tokens)},
        )
    )

    assert session.calls[0]["headers"]["X-CSRF-Token"] == "first"
    assert session.calls[1]["headers"]["X-CSRF-Token"] == "second"


def test_sign_in_page_instead_of_json_is_an_auth_error() -> None:
    """An expired session gets answered with HTML and a 200."""
    with pytest.raises(TextNowAuthError):
        _parse_json_body("<!DOCTYPE html><html>Sign in</html>")


def test_unreadable_body_is_an_api_error() -> None:
    """Anything else unexpected is not blamed on the credentials."""
    with pytest.raises(TextNowApiError):
        _parse_json_body("not json at all")

    assert _parse_json_body("") == {}


def test_messages_are_read_from_either_payload_shape() -> None:
    """The API answers with a list or a wrapper object."""
    assert _extract_messages([{"id": 1}]) == [{"id": 1}]
    assert _extract_messages({"messages": [{"id": 2}]}) == [{"id": 2}]
    assert _extract_messages({"result": [{"id": 3}]}) == [{"id": 3}]
    assert _extract_messages({"unexpected": True}) == []
    assert _extract_messages(None) == []


def test_processed_ids_are_trimmed_to_the_newest() -> None:
    """The store must not grow forever."""
    trimmed = _trim_message_ids({str(index) for index in range(1500)})

    assert len(trimmed) == 1000
    assert "1499" in trimmed
    assert "0" not in trimmed


class _TestableCoordinator(TextNowDataUpdateCoordinator):
    """Coordinator with only the Home Assistant pieces it really touches."""

    def __init__(self, failure: Exception | None) -> None:
        self.auth_failed = False
        self.last_success = None
        self._config: dict[str, Any] = {"polling_interval": 30}
        self._cookies: dict[str, str] = {}
        self._failures = 0
        self._failure = failure
        self.reported: list[str] = []
        self.saved = 0
        self.update_interval = None
        self.hass = FakeHass()
        self.entry = self.hass.make_entry()

    def _async_persist_cookies(self, force: bool = False) -> None:
        self.saved += 1

    async def _poll_unread_messages(self) -> None:
        if self._failure is not None:
            raise self._failure

    async def _cleanup_expired_pending(self) -> None:
        return None

    def _async_report_auth_problem(self, err: TextNowAuthError) -> None:
        self.reported.append(type(err).__name__)

    def _async_clear_auth_problem(self) -> None:
        self.reported.clear()


def test_rotated_cookies_are_followed() -> None:
    """The value TextNow just set is the value the next call must send."""
    coordinator = _TestableCoordinator(None)
    coordinator._cookies = {"connect.sid": "old", "_csrf": "c1"}

    rotated = SimpleCookie()
    rotated["connect.sid"] = "new"
    rotated["connect.sid"]["domain"] = ".textnow.com"
    rotated["XSRF-TOKEN"] = "fresh-token"
    coordinator._async_absorb_cookies(rotated)

    assert coordinator._cookies["connect.sid"] == "new"
    assert coordinator.saved == 1
    # The CSRF header follows the rotated token instead of replaying the old one
    assert coordinator._headers_factory()()["X-CSRF-Token"] == "fresh-token"


def test_deleted_cookies_are_dropped() -> None:
    """A cookie cleared by the server must not be replayed."""
    coordinator = _TestableCoordinator(None)
    coordinator._cookies = {"connect.sid": "old", "_px3": "px"}

    cleared = SimpleCookie()
    cleared["_px3"] = ""
    cleared["_px3"]["max-age"] = "0"
    coordinator._async_absorb_cookies(cleared)

    assert "_px3" not in coordinator._cookies
    assert coordinator._cookies["connect.sid"] == "old"


def test_unchanged_cookies_are_not_written_back() -> None:
    """Every poll rotating nothing must not write the config entry."""
    coordinator = _TestableCoordinator(None)
    coordinator._cookies = {"connect.sid": "old"}

    same = SimpleCookie()
    same["connect.sid"] = "old"
    coordinator._async_absorb_cookies(same)

    assert coordinator.saved == 0


def test_expired_session_asks_home_assistant_for_reauth() -> None:
    """The 401 has to leave the coordinator, not get logged and dropped."""
    coordinator = _TestableCoordinator(TextNowAuthError("expired"))

    with pytest.raises(ConfigEntryAuthFailed):
        _run(coordinator._async_update_data())

    assert coordinator.auth_failed is True
    assert coordinator.reported == ["TextNowAuthError"]
    # Polling slows right down so an expired session cannot make thousands of
    # requests a day, but it must not stop: see the deadlock test below.
    assert coordinator.update_interval == AUTH_RECOVERY_INTERVAL


def test_an_expired_session_can_recover_without_a_restart() -> None:
    """The bug that locked an account out until Home Assistant restarted.

    auth_failed was only ever cleared by a poll, and the auth failure set
    update_interval to None, which stopped every future poll. Pausing removed
    the one mechanism that could clear the flag, so the panel said "reconnect"
    for ever and the send controls stayed disabled.
    """
    coordinator = _TestableCoordinator(TextNowAuthError("expired"))

    with pytest.raises(ConfigEntryAuthFailed):
        _run(coordinator._async_update_data())
    assert coordinator.auth_failed is True

    # Home Assistant can only schedule another poll if an interval survives.
    assert coordinator.update_interval is not None

    # That next poll is what notices the session working again.
    coordinator._failure = None
    _run(coordinator._async_update_data())

    assert coordinator.auth_failed is False
    assert coordinator.update_interval.total_seconds() == 30


def test_the_refresh_button_re_arms_a_slowed_account() -> None:
    """The panel's refresh must not leave the account on the slow interval."""
    coordinator = _TestableCoordinator(TextNowAuthError("expired"))

    with pytest.raises(ConfigEntryAuthFailed):
        _run(coordinator._async_update_data())

    coordinator.async_rearm_polling()

    assert coordinator.auth_failed is False
    assert coordinator.update_interval.total_seconds() == 30


def test_only_the_bot_block_gets_a_repair_card_of_its_own(monkeypatch) -> None:
    """Asking for a reauth already puts a card in Repairs.

    Two cards for one problem is noise, so the integration only adds one when
    it has different steps to offer.
    """
    raised: list[str] = []
    monkeypatch.setattr(
        coordinator_module.ir,
        "async_create_issue",
        lambda hass, domain, issue_id, **kwargs: raised.append(kwargs["translation_key"]),
    )

    coordinator = _TestableCoordinator(None)
    coordinator.hass = None
    coordinator.entry = SimpleNamespace(title="demo", entry_id="e1")

    TextNowDataUpdateCoordinator._async_report_auth_problem(
        coordinator, TextNowAuthError("expired")
    )
    assert raised == []

    TextNowDataUpdateCoordinator._async_report_auth_problem(
        coordinator, TextNowBlockedError("blocked")
    )
    assert raised == ["bot_blocked"]


def test_network_trouble_backs_off_and_keeps_polling() -> None:
    """Transient errors stay UpdateFailed and slow the polling down."""
    coordinator = _TestableCoordinator(TextNowConnectionError("no answer"))

    for expected in (60, 120, 240):
        with pytest.raises(UpdateFailed):
            _run(coordinator._async_update_data())
        assert coordinator.update_interval.total_seconds() == expected

    assert coordinator.auth_failed is False


def test_backoff_is_capped() -> None:
    """The interval never runs away."""
    coordinator = _TestableCoordinator(TextNowConnectionError("no answer"))

    for _ in range(20):
        with pytest.raises(UpdateFailed):
            _run(coordinator._async_update_data())

    assert coordinator.update_interval.total_seconds() == 900


def test_a_good_poll_restores_the_configured_interval() -> None:
    """Recovery does not need a restart."""
    coordinator = _TestableCoordinator(TextNowConnectionError("no answer"))

    with pytest.raises(UpdateFailed):
        _run(coordinator._async_update_data())
    coordinator._failure = None
    _run(coordinator._async_update_data())

    assert coordinator.update_interval.total_seconds() == 30
    assert coordinator.last_success is not None
    assert coordinator.reported == []
