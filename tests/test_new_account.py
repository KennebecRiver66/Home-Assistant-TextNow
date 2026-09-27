"""What a brand-new TextNow account does, and how it must be reported.

TextNow holds a new account back from the web for up to about two days after
signing up, while the phone app works immediately. During the wait the session
is genuinely valid -- checking for messages works -- and sending is refused.
Read as an authentication problem that becomes a sign-in prompt the user can
never satisfy, which is why these refusals are classified on their own.
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.helpers import issue_registry as ir

from custom_components.textnow import coordinator as coordinator_module
from custom_components.textnow.const import MIN_POLLING_INTERVAL
from custom_components.textnow.coordinator import (
    TextNowApiError,
    TextNowAuthError,
    TextNowDataUpdateCoordinator,
    TextNowWebAccessError,
    async_api_request,
)
from fakes import FakeHass
from test_api_errors import _FakeResponse, _FakeSession, _headers

# How the web client puts it while an account is still being enabled.
WEB_SETUP_BODY = (
    '{"error_code":"PERMISSION_DENIED","message":"This account is not yet '
    'set up for web access"}'
)
STILL_SETTING_UP_BODY = '{"error":"Uh-oh! Your account is still being set up"}'
BAD_NUMBER_BODY = '{"error_code":"INVALID_CONTACT_VALUE"}'


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coordinator_module, "RETRY_DELAY", 0)


def _request(session: _FakeSession, method: str = "POST") -> Any:
    return _run(
        async_api_request(
            session,
            method,
            "https://example.invalid/api/users/demo/messages",
            headers_factory=_headers,
        )
    )


def test_a_new_account_is_not_blamed_on_the_cookies() -> None:
    """The refusal that used to read as an expired session.

    A 403 with no bot markers means new cookies are needed -- except when
    TextNow has said in the same breath that the account is the problem. Two
    days of a sign-in prompt that fresh cookies cannot clear is the worst
    possible answer to a wait the user cannot do anything about.
    """
    session = _FakeSession([_FakeResponse(403, WEB_SETUP_BODY)])

    with pytest.raises(TextNowWebAccessError) as err:
        _request(session)

    assert not isinstance(err.value, TextNowAuthError)
    assert "48 hours" in str(err.value)
    # And TextNow's own words are kept, not replaced with a guess.
    assert "not yet set up for web access" in str(err.value)


def test_the_other_wording_is_recognised_too() -> None:
    """The web app and the API do not phrase it the same way."""
    session = _FakeSession([_FakeResponse(400, STILL_SETTING_UP_BODY)])

    with pytest.raises(TextNowWebAccessError):
        _request(session)


def test_a_refusal_that_explains_itself_is_not_retried() -> None:
    """TextNow will not change its mind, and this session is watched."""
    session = _FakeSession([_FakeResponse(403, WEB_SETUP_BODY)])

    with pytest.raises(TextNowWebAccessError):
        _request(session)

    assert len(session.calls) == 1


def test_what_textnow_said_reaches_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The report asked for exactly this: a reason in the log.

    A send refused inside an automation may never be read by anyone, so the
    explanation cannot live only in the raised error.
    """
    session = _FakeSession([_FakeResponse(403, WEB_SETUP_BODY)])

    with caplog.at_level(logging.WARNING, logger=coordinator_module.__name__):
        with pytest.raises(TextNowWebAccessError):
            _request(session)

    assert "not yet set up for web access" in caplog.text
    assert "48 hours" in caplog.text


def test_any_other_refusal_is_logged_with_what_textnow_said(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A refusal nobody has an explanation for still has to be visible."""
    session = _FakeSession([_FakeResponse(400, BAD_NUMBER_BODY)])

    with caplog.at_level(logging.WARNING, logger=coordinator_module.__name__):
        with pytest.raises(TextNowApiError):
            _request(session)

    assert "INVALID_CONTACT_VALUE" in caplog.text


def test_a_bad_number_is_not_mistaken_for_a_new_account() -> None:
    """The classification only fires on what TextNow actually said."""
    session = _FakeSession([_FakeResponse(400, BAD_NUMBER_BODY)])

    with pytest.raises(TextNowApiError) as err:
        _request(session)

    assert not isinstance(err.value, TextNowWebAccessError)


class _Account(TextNowDataUpdateCoordinator):
    """Only the pieces the reporting touches."""

    def __init__(self) -> None:
        self.hass = FakeHass()
        self.entry = SimpleNamespace(
            title="demo_account", entry_id="e1", domain="textnow"
        )
        self._config: dict[str, Any] = {}
        self.last_update_success = True
        self.auth_failed = False
        self.created: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    @property
    def username(self) -> str:
        return "demo_account"


@pytest.fixture
def account(monkeypatch: pytest.MonkeyPatch) -> _Account:
    acct = _Account()
    monkeypatch.setattr(
        coordinator_module.ir,
        "async_create_issue",
        lambda hass, domain, issue_id, **kwargs: acct.created.append(
            {"issue_id": issue_id, **kwargs}
        ),
    )
    monkeypatch.setattr(
        coordinator_module.ir,
        "async_delete_issue",
        lambda hass, domain, issue_id: acct.deleted.append(issue_id),
    )
    return acct


def test_the_wait_gets_a_repair_notice_of_its_own(account: _Account) -> None:
    """Different from every other failure here in having no steps to offer."""
    account._async_report_web_setup_problem()

    assert len(account.created) == 1
    issue = account.created[0]
    assert issue["issue_id"] == "web_not_ready_e1"
    assert issue["translation_key"] == "web_not_ready"
    # A wait is not an error: nothing is broken and nothing needs doing.
    assert issue["severity"] is ir.IssueSeverity.WARNING
    assert issue["translation_placeholders"] == {"account": "demo_account"}


def test_a_message_getting_through_clears_the_notice(account: _Account) -> None:
    """A successful poll does not prove sending works, so a send must clear it."""
    account._async_clear_web_setup_problem()

    assert account.deleted == ["web_not_ready_e1"]


def test_a_refused_send_suggests_the_check_that_settles_it(
    account: _Account,
) -> None:
    """Reading works, so the hint is a fact plus one thing to try."""
    hinted = account._async_add_refusal_hint("POST", TextNowApiError("refused"))

    assert "textnow.com" in str(hinted)
    assert "48 hours" in str(hinted)
    assert str(hinted).startswith("refused")


def test_nothing_is_added_when_reading_is_broken_too(account: _Account) -> None:
    """With the whole session failing, a send is not the interesting part."""
    account.last_update_success = False
    original = TextNowApiError("refused")

    assert account._async_add_refusal_hint("POST", original) is original


def test_nothing_is_added_to_a_failure_that_was_not_a_send(
    account: _Account,
) -> None:
    original = TextNowApiError("refused")

    assert account._async_add_refusal_hint("GET", original) is original


def test_the_polling_floor_holds(account: _Account) -> None:
    """The answer to "can I poll every second?" is enforced, not just written.

    One second is 86,400 requests a day at TextNow, on the session its bot
    protection is already watching. The floor is what keeps a good intention
    from getting an account blocked.
    """
    account._config = {"polling_interval": 1}
    assert account.polling_interval == MIN_POLLING_INTERVAL

    account._config = {"polling_interval": 45}
    assert account.polling_interval == 45
