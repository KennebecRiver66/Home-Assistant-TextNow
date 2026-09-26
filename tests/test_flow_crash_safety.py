"""A step that fails must still answer with a form.

A config flow step that raises leaves the flow registered with nothing to
render. It cannot be seen on the integrations page, so the user cannot answer
it or dismiss it, and it is still enough to make Home Assistant decline to
open a real sign-in prompt in its place. One bad paste therefore turned into
an account that could not be signed back in at all.
"""
from __future__ import annotations

import asyncio
from http.cookies import CookieError
from typing import Any

import pytest

from custom_components.textnow import config_flow as config_flow_module
from custom_components.textnow.config_flow import TextNowConfigFlow


class _Flow(TextNowConfigFlow):
    """The flow's steps without a flow manager behind them."""

    def __init__(self) -> None:
        super().__init__()
        self.hass = None
        self.aborted: list[str] = []

    def async_show_form(self, **kwargs: Any) -> dict[str, Any]:
        return {"type": "form", **kwargs}

    def async_abort(self, *, reason: str, **_kwargs: Any) -> dict[str, Any]:
        self.aborted.append(reason)
        return {"type": "abort", "reason": reason}

    def add_suggested_values_to_schema(self, schema, _suggested):
        return schema


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "failure",
    [
        CookieError("Illegal key"),
        ValueError("nonsense in the paste"),
        RuntimeError("something nobody predicted"),
    ],
)
def test_a_step_that_blows_up_still_renders_a_form(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    """Whatever goes wrong, the user gets a form they can retry from."""

    async def _explode(*_args: Any, **_kwargs: Any) -> None:
        raise failure

    monkeypatch.setattr(config_flow_module, "async_validate_account", _explode)
    flow = _Flow()

    result = _run(flow.async_step_user({"username": "", "cookie_string": "anything"}))

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "unknown"}


def test_the_sign_in_step_survives_it_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """This is the step the reported lockup came through."""

    async def _explode(*_args: Any, **_kwargs: Any) -> None:
        raise CookieError("Illegal key '-b ^\"ppid'")

    monkeypatch.setattr(config_flow_module, "async_validate_account", _explode)
    flow = _Flow()
    flow._reauth_entry = type(
        "Entry", (), {"data": {"username": "demo_account"}}
    )()

    result = _run(
        flow.async_step_reauth_confirm({"cookie_string": 'curl -b ^"ppid=x^"'})
    )

    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "unknown"}


def test_a_missing_account_aborts_rather_than_raising() -> None:
    """Nothing to sign back in to, so end the flow instead of leaving it open."""
    flow = _Flow()

    def _gone() -> None:
        raise ValueError("entry is gone")

    flow._get_reauth_entry = _gone

    result = _run(flow.async_step_reauth({}))

    assert result["type"] == "abort"
    assert flow.aborted == ["reauth_failed"]


def test_an_unreadable_paste_is_a_form_error_not_a_crash() -> None:
    """The parser is hardened, but the form must not depend on that holding."""

    def _explode(_text: str) -> None:
        raise CookieError("Illegal key")

    original = config_flow_module.parse_cookie_string
    config_flow_module.parse_cookie_string = _explode
    try:
        _username, credentials, errors = _run(
            config_flow_module.async_validate_account(None, "demo", "rubbish")
        )
    finally:
        config_flow_module.parse_cookie_string = original

    assert errors == {"base": "no_cookies"}
    assert credentials == {}
