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
from custom_components.textnow.coordinator import (
    TextNowApiError,
    TextNowAuthError,
    TextNowBlockedError,
    TextNowConnectionError,
    TextNowDataUpdateCoordinator,
    _extract_messages,
    _parse_json_body,
    async_api_request,
)
from custom_components.textnow.storage import _trim_message_ids

PERIMETERX_BODY = (
    "<html><head><title>Access to this page has been denied</title>"
    "<script>window._pxAppId</script>PerimeterX</html>"
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
    session = _FakeSession([_FakeResponse(403, '{"error_code":"FORBIDDEN"}')])

    with pytest.raises(TextNowAuthError) as err:
        _run(
            async_api_request(
                session, "GET", "https://example.invalid", headers_factory=_headers
            )
        )

    assert not isinstance(err.value, TextNowBlockedError)


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
    """Coordinator without a Home Assistant instance behind it."""

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

    def _async_persist_cookies(self) -> None:
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
    # Polling stops so an expired session cannot make thousands of requests
    assert coordinator.update_interval is None


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
