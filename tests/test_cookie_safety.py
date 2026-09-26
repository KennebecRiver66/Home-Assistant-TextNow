"""Cookie pastes that used to break the integration.

A Windows "Copy as cURL (cmd)" paste put `-b ^"ppid` into the cookie jar,
which aiohttp rejected with http.cookies.CookieError. That is neither a
ClientError nor a HomeAssistantError, so it escaped every handler, showed
the user "unexpected error", and -- once stored -- broke every later
request, not just the one that validated the paste.

Every value here is made up.
"""
from __future__ import annotations

from http.cookies import SimpleCookie

import pytest

from custom_components.textnow.cookies import (
    cookie_header,
    is_valid_cookie_name,
    parse_cookie_string,
    sanitize_cookies,
)
from custom_components.textnow.coordinator import build_headers, cookies_from_entry_data

CONNECT_SID = "s%3Afake-session.fake-signature"
CSRF = "s%3Afake-csrf.fake-signature"
XSRF = "fake-xsrf-token"

# What Chrome on Windows actually puts on the clipboard, carets and all.
CMD_CURL = (
    'curl ^"https://www.textnow.com/messaging^" ^\n'
    '  -H ^"accept: text/html,application/xhtml+xml^" ^\n'
    f'  -b ^"ppid=fake-ppid; connect.sid={CONNECT_SID}; _csrf={CSRF}; '
    f'XSRF-TOKEN={XSRF}^" ^\n'
    '  -H ^"sec-ch-ua: ^\\^"Chromium^\\^";v=^\\^"153^\\^"^" ^\n'
    "  --compressed"
)

BASH_CURL = (
    "curl 'https://www.textnow.com/messaging' \\\n"
    "  -H 'accept: text/html,application/xhtml+xml' \\\n"
    f"  -b 'ppid=fake-ppid; connect.sid={CONNECT_SID}; _csrf={CSRF}; "
    f"XSRF-TOKEN={XSRF}' \\\n"
    "  --compressed"
)


def test_a_windows_cmd_curl_paste_parses_instead_of_crashing() -> None:
    """The exact paste from the crash report."""
    cookies = parse_cookie_string(CMD_CURL)

    assert cookies == {
        "ppid": "fake-ppid",
        "connect.sid": CONNECT_SID,
        "_csrf": CSRF,
        "XSRF-TOKEN": XSRF,
    }


def test_a_bash_curl_paste_parses_the_same_way() -> None:
    """Both menu entries have to lead to the same place."""
    assert parse_cookie_string(BASH_CURL) == parse_cookie_string(CMD_CURL)


def test_shell_arguments_never_become_cookie_names() -> None:
    """`-b ^"ppid` is a shell fragment, not a cookie."""
    for name in ('-b ^"ppid', "-H", "--compressed", "sec-ch-ua: x", 'a"b', "a;b", "a=b"):
        assert not is_valid_cookie_name(name)

    for name in ("connect.sid", "_csrf", "XSRF-TOKEN", "_px3", "ppid"):
        assert is_valid_cookie_name(name)


def test_a_curl_paste_only_yields_its_cookie_arguments() -> None:
    """Nothing from the rest of the command line gets stored."""
    cookies = parse_cookie_string(CMD_CURL)

    assert all(is_valid_cookie_name(name) for name in cookies)
    assert not any("sec-ch-ua" in name for name in cookies)


def test_the_token_survives_the_paste_intact() -> None:
    """A mangled XSRF-TOKEN reads server-side as a forged request.

    The old parser returned `fake-xsrf-token^" ^`, so even a paste that got
    past validation produced requests TextNow would refuse.
    """
    assert parse_cookie_string(CMD_CURL)["XSRF-TOKEN"] == XSRF


@pytest.mark.parametrize(
    "bad",
    [
        {'-b ^"ppid': "value"},
        {"has space": "value"},
        {'quo"te': "value"},
        {"semi;colon": "value"},
        {"": "value"},
        {"good": "has;semicolon"},
        {"good": "has space"},
        {"good": ""},
    ],
)
def test_unusable_cookies_are_dropped_rather_than_stored(bad: dict) -> None:
    assert sanitize_cookies(bad) == {}


def test_the_cookie_header_is_built_without_aiohttp() -> None:
    """Building the header ourselves keeps SimpleCookie out of the path."""
    header = cookie_header({"connect.sid": CONNECT_SID, "XSRF-TOKEN": XSRF})

    assert header == f"connect.sid={CONNECT_SID}; XSRF-TOKEN={XSRF}"


def test_headers_carry_the_cookies_and_the_matching_token() -> None:
    headers = build_headers({"connect.sid": CONNECT_SID, "XSRF-TOKEN": XSRF})

    assert headers["Cookie"] == f"connect.sid={CONNECT_SID}; XSRF-TOKEN={XSRF}"
    assert headers["X-CSRF-Token"] == XSRF


def test_an_account_stored_with_a_bad_cookie_still_works() -> None:
    """A entry saved by an older release must not break every request.

    Without this, one bad paste poisoned sends and polls alike until the
    account was deleted and added again.
    """
    cookies = cookies_from_entry_data(
        {
            "cookies": {'-b ^"ppid': "junk", "connect.sid": CONNECT_SID},
            "connect_sid": CONNECT_SID,
            "csrf": CSRF,
        }
    )

    assert cookies == {"connect.sid": CONNECT_SID, "_csrf": CSRF}
    assert "Cookie" in build_headers(cookies)


def test_a_logout_signalled_by_an_expiry_date_is_a_delete() -> None:
    """Only max-age was checked, so an expires-style logout was replayed."""
    from custom_components.textnow.coordinator import _cookie_is_expired

    past = SimpleCookie()
    past["connect.sid"] = "dead"
    past["connect.sid"]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
    assert _cookie_is_expired(past["connect.sid"]) is True

    future = SimpleCookie()
    future["connect.sid"] = "alive"
    future["connect.sid"]["expires"] = "Tue, 01 Jan 2999 00:00:00 GMT"
    assert _cookie_is_expired(future["connect.sid"]) is False

    plain = SimpleCookie()
    plain["connect.sid"] = "alive"
    assert _cookie_is_expired(plain["connect.sid"]) is False
