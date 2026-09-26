"""Tests for reading whatever cookie format the user pastes.

Every value in here is made up.
"""
from __future__ import annotations

from custom_components.textnow.config_flow import (
    extract_username,
    normalize_username,
    parse_cookie_string,
)
from custom_components.textnow.coordinator import cookies_from_entry_data, csrf_token

CONNECT_SID = "s%3Afake-session-value.fake-signature"
CSRF = "s%3Afake-csrf.fake-signature"
XSRF = "fake-xsrf-token"


def test_parses_a_cookie_header_line() -> None:
    """A cookie line copied from the network tab."""
    pasted = f"connect.sid={CONNECT_SID}; _csrf={CSRF}; XSRF-TOKEN={XSRF}"

    assert parse_cookie_string(pasted) == {
        "connect.sid": CONNECT_SID,
        "_csrf": CSRF,
        "XSRF-TOKEN": XSRF,
    }


def test_parses_a_cookie_header_with_prefix_and_newlines() -> None:
    """Devtools sometimes includes the header name and wraps lines."""
    pasted = f"cookie: connect.sid={CONNECT_SID};\n_csrf={CSRF}\n"

    cookies = parse_cookie_string(pasted)

    assert cookies == {"connect.sid": CONNECT_SID, "_csrf": CSRF}


def test_parses_a_copy_as_curl_command() -> None:
    """Chrome's "Copy as cURL" output."""
    pasted = (
        "curl 'https://www.textnow.com/api/users/me/messages' "
        "-H 'accept: application/json' "
        f"-H 'cookie: connect.sid={CONNECT_SID}; _px3=fake-px' "
        "--compressed"
    )

    assert parse_cookie_string(pasted) == {
        "connect.sid": CONNECT_SID,
        "_px3": "fake-px",
    }


def test_parses_a_cookie_manager_json_export() -> None:
    """The JSON shape cookie editor extensions produce."""
    pasted = (
        '[{"name": "connect.sid", "value": "' + CONNECT_SID + '", '
        '"domain": ".textnow.com"}, '
        '{"name": "XSRF-TOKEN", "value": "' + XSRF + '"}]'
    )

    assert parse_cookie_string(pasted) == {
        "connect.sid": CONNECT_SID,
        "XSRF-TOKEN": XSRF,
    }


def test_parses_the_devtools_cookie_table() -> None:
    """The Application tab copies tab separated rows."""
    pasted = (
        f"connect.sid\t{CONNECT_SID}\t.textnow.com\t/\tSession\n"
        f"XSRF-TOKEN\t{XSRF}\t.textnow.com\t/\tSession"
    )

    assert parse_cookie_string(pasted) == {
        "connect.sid": CONNECT_SID,
        "XSRF-TOKEN": XSRF,
    }


def test_ignores_set_cookie_attributes() -> None:
    """Attributes are not cookies."""
    pasted = (
        f"set-cookie: connect.sid={CONNECT_SID}; Path=/; HttpOnly; "
        "Secure; SameSite=Lax; Domain=.textnow.com; Max-Age=3600"
    )

    assert parse_cookie_string(pasted) == {"connect.sid": CONNECT_SID}


def test_empty_paste_returns_nothing() -> None:
    """An empty paste is reported as no cookies, not as a crash."""
    assert parse_cookie_string("") == {}
    assert parse_cookie_string("   \n  ") == {}


def test_username_is_normalized() -> None:
    """People paste their handle in several shapes."""
    assert normalize_username("  @Example  ") == "Example"
    assert normalize_username("example@textnow.me") == "example"
    assert normalize_username("example") == "example"


def test_stored_cookies_include_the_whole_paste() -> None:
    """Bot protection cookies are replayed as well as the session ones."""
    entry_data = {
        "connect_sid": CONNECT_SID,
        "csrf": CSRF,
        "xsrf_token": XSRF,
        "cookies": {"_px3": "fake-px", "connect.sid": CONNECT_SID},
    }

    cookies = cookies_from_entry_data(entry_data)

    assert cookies["_px3"] == "fake-px"
    assert cookies["connect.sid"] == CONNECT_SID
    assert cookies["XSRF-TOKEN"] == XSRF


def test_accounts_from_older_versions_still_work() -> None:
    """Entries saved before the cookie bag existed keep working."""
    cookies = cookies_from_entry_data(
        {"connect_sid": CONNECT_SID, "csrf": CSRF, "xsrf_token": ""}
    )

    assert cookies == {"connect.sid": CONNECT_SID, "_csrf": CSRF}


def test_csrf_token_prefers_the_xsrf_cookie() -> None:
    """The XSRF-TOKEN cookie holds the plain token."""
    assert csrf_token({"XSRF-TOKEN": XSRF, "_csrf": CSRF}) == XSRF


def test_csrf_token_decodes_the_csrf_cookie_as_fallback() -> None:
    """Without XSRF-TOKEN the token comes from the encoded _csrf cookie."""
    assert csrf_token({"_csrf": "s%3Aabc.def"}) == "s:abc.def"
    assert csrf_token({"_csrf": "plain"}) == "plain"
    assert csrf_token({}) == ""


def test_username_is_read_from_a_pasted_request() -> None:
    """A cURL paste carries the account name in the URL."""
    pasted = (
        "curl 'https://www.textnow.com/api/users/example_user/messages"
        "?start_message_id=0' -H 'cookie: connect.sid=x'"
    )

    assert extract_username(pasted) == "example_user"


def test_username_is_read_from_a_json_blob() -> None:
    """Some pastes contain the user object instead."""
    assert extract_username('{"username": "example_user", "id": 1}') == "example_user"


def test_username_extraction_gives_up_quietly() -> None:
    """A plain cookie line has no username in it."""
    assert extract_username("connect.sid=abc; _csrf=def") == ""
    assert extract_username("https://www.textnow.com/api/users/me/messages") == ""
