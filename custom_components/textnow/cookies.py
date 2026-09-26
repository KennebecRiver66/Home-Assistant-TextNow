"""Reading, validating and sending browser cookies.

Everything a user can paste arrives here, so this module assumes the input
is hostile by accident: shell fragments, Windows ``cmd`` escaping, half a
Set-Cookie header, or a cookie manager's JSON. Nothing leaves here unless it
is a cookie name and value that can safely go on the wire.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Final

_LOGGER = logging.getLogger(__name__)

# Cookie attributes that show up when a Set-Cookie header or a cookie
# manager export is pasted instead of a plain cookie line.
COOKIE_ATTRIBUTES: Final = {
    "domain",
    "expires",
    "httponly",
    "max-age",
    "partitioned",
    "path",
    "priority",
    "samesite",
    "secure",
    "version",
}

# RFC 6265 cookie-name is an RFC 2616 token: any CHAR except CTLs and
# separators. Anything else is not a cookie, it is wreckage from the paste.
_SEPARATORS: Final = '()<>@,;:\\"/[]?={} \t'
_VALID_NAME: Final = re.compile(
    r"^[^\x00-\x20\x7f" + re.escape(_SEPARATORS) + r"]+$"
)

# RFC 6265 cookie-octet, plus the surrounding quotes a value may carry.
_INVALID_VALUE: Final = re.compile(r'[\x00-\x1f\x7f;,\s\\"]')


def is_valid_cookie_name(name: str) -> bool:
    """Return whether a name can be sent as a cookie name.

    A leading hyphen is a valid token but is always a command line flag in
    practice, so it is refused: no real cookie is named -H.
    """
    if not name or name.startswith("-"):
        return False
    return bool(_VALID_NAME.match(name))


def is_valid_cookie_value(value: str) -> bool:
    """Return whether a value can be sent unquoted."""
    return not _INVALID_VALUE.search(value)


def sanitize_cookies(raw: dict[str, str]) -> dict[str, str]:
    """Drop anything that is not a usable cookie.

    A bad name used to reach aiohttp and raise http.cookies.CookieError,
    which is neither a ClientError nor a HomeAssistantError, so it escaped
    every handler and surfaced as "unexpected error" with a traceback.
    """
    clean: dict[str, str] = {}

    for name, value in raw.items():
        name = str(name).strip()
        value = str(value).strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]

        if not is_valid_cookie_name(name):
            _LOGGER.debug("Ignoring unusable cookie name %r from the paste", name)
            continue
        if not value or not is_valid_cookie_value(value):
            _LOGGER.debug("Ignoring unusable value for cookie %r", name)
            continue
        clean[name] = value

    return clean


def cookie_header(cookies: dict[str, str]) -> str:
    """Return the Cookie header for a set of cookies.

    Built here rather than handed to aiohttp, which runs every name and
    value through http.cookies.SimpleCookie and raises CookieError on
    anything it dislikes. The values are already validated, so this cannot
    produce a malformed header.
    """
    return "; ".join(
        f"{name}={value}" for name, value in sanitize_cookies(cookies).items()
    )


def _strip_shell_escapes(text: str) -> str:
    """Undo the quoting a shell would have removed.

    Windows "Copy as cURL (cmd)" escapes with a caret, so the clipboard holds
    ``-b ^"ppid=...^"``. Left alone, the parser reads ``-b ^"ppid`` as a
    cookie name, which is the exact string in the reported crash.
    """
    # Line continuations first, so a wrapped command becomes one line.
    text = re.sub(r"\^\r?\n", "", text)
    text = re.sub(r"\\\r?\n", " ", text)

    if '^"' in text:
        # In cmd the caret escapes the next character, whatever it is.
        text = re.sub(r"\^(.)", r"\1", text, flags=re.DOTALL)

    return text


def _unquote_shell_value(text: str) -> str:
    """Return a quoted shell argument's contents."""
    return (
        text.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
    )


# -b/--cookie carries the cookies directly; -H 'cookie: ...' carries them as a
# header. Chrome emits either depending on the platform and the request.
_CURL_COOKIES: Final = re.compile(
    r"""(?:-b|--cookie)[ \t]+\$?(['"])(?P<bare>(?:\\.|(?!\1).)*)\1"""
    r"""|(?:-H|--header)[ \t]+\$?(['"])[ \t]*cookie[ \t]*:[ \t]*"""
    r"""(?P<header>(?:\\.|(?!\3).)*)\3""",
    re.IGNORECASE | re.DOTALL,
)


def _parse_json_cookies(text: str) -> dict[str, str]:
    """Return cookies from a cookie manager JSON export."""
    if not text.startswith(("[", "{")):
        return {}
    try:
        payload = json.loads(text)
    except ValueError:
        return {}

    if isinstance(payload, dict):
        if isinstance(payload.get("cookies"), list):
            payload = payload["cookies"]
        else:
            return {
                str(key): str(value)
                for key, value in payload.items()
                if isinstance(value, str)
            }

    cookies: dict[str, str] = {}
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("key")
            value = item.get("value")
            if name and value is not None:
                cookies[str(name)] = str(value)
    return cookies


def _parse_cookie_pairs(text: str) -> dict[str, str]:
    """Return cookies from a cookie header, or a devtools cookie table."""
    cookies: dict[str, str] = {}

    for line in text.replace("\r", "").split("\n"):
        line = re.sub(r"^\s*(?:set-)?cookie\s*:\s*", "", line, flags=re.IGNORECASE)
        if not line.strip():
            continue

        # The devtools Application tab copies one tab separated cookie per line.
        if "\t" in line and "=" not in line.split("\t")[0]:
            fields = [field for field in line.split("\t") if field.strip()]
            if len(fields) >= 2:
                cookies[fields[0].strip()] = fields[1].strip()
            continue

        for part in line.split(";"):
            part = part.strip()
            if not part:
                continue
            key, sep, value = part.partition("=")
            if not sep:
                continue
            key = key.strip()
            value = value.strip()
            if not key or not value or key.lower() in COOKIE_ATTRIBUTES:
                continue
            cookies[key] = value

    return cookies


def parse_cookie_string(cookie_string: str) -> dict[str, str]:
    """Return the cookies found in whatever the user pasted.

    Accepts a cookie header line, the output of document.cookie, "Copy as
    cURL" in either bash or Windows cmd form, the devtools cookie table and
    the JSON exports produced by cookie manager browser extensions.

    Anything that survives parsing is still validated, so a paste this does
    not understand yields fewer cookies rather than a broken request later.
    """
    if not cookie_string:
        return {}

    text = cookie_string.strip()

    cookies = _parse_json_cookies(text)
    if cookies:
        return sanitize_cookies(cookies)

    text = _strip_shell_escapes(text)

    # A cURL command holds cookies in known arguments. Reading only those
    # keeps the rest of the command line out of the cookie jar.
    from_curl: dict[str, str] = {}
    for match in _CURL_COOKIES.finditer(text):
        payload = match.group("bare") or match.group("header") or ""
        from_curl.update(_parse_cookie_pairs(_unquote_shell_value(payload)))
    if from_curl:
        return sanitize_cookies(from_curl)

    return sanitize_cookies(_parse_cookie_pairs(text))
