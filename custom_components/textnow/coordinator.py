"""DataUpdateCoordinator for TextNow."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from http.cookies import Morsel, SimpleCookie
from typing import Any, Final
from urllib.parse import unquote

import aiohttp

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EVENT_MESSAGE_RECEIVED,
    EVENT_REPLY_PARSED,
    ATTR_PHONE,
    ATTR_TEXT,
    ATTR_MESSAGE_ID,
    ATTR_TIMESTAMP,
    ATTR_CONTACT_ID,
    ATTR_TYPE,
    ATTR_VALUE,
    ATTR_RAW_TEXT,
    ATTR_OPTION_INDEX,
    CONF_COOKIES,
    CONF_KEEPALIVE_DAYS,
    CONF_KEEPALIVE_MESSAGE,
    CONF_KEEPALIVE_PHONE,
    CONF_POLLING_INTERVAL,
    CONF_USERNAME,
    COOKIE_HELP_URL,
    DEFAULT_KEEPALIVE_DAYS,
    DEFAULT_KEEPALIVE_MESSAGE,
    DEFAULT_POLLING_INTERVAL,
    KEEPALIVE_RETRY_INTERVAL,
    AUTH_RECOVERY_INTERVAL,
    MAX_BACKOFF_INTERVAL,
    MAX_KEEPALIVE_DAYS,
    MIN_KEEPALIVE_DAYS,
    MIN_POLLING_INTERVAL,
)
from .cookies import (
    cookie_header,
    is_valid_cookie_name,
    is_valid_cookie_value,
    sanitize_cookies,
)
from .parsing import parse_reply
from .storage import TextNowStorage

_LOGGER = logging.getLogger(__name__)

BASE_URL: Final = "https://www.textnow.com"

# Keep the client fingerprint coherent and current: TextNow sits behind
# PerimeterX, which scores requests that claim to be Chrome but omit the
# headers a real Chrome always sends.
CHROME_VERSION: Final = "153"
USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/{CHROME_VERSION}.0.0.0 Safari/537.36"
)
BROWSER_HEADERS: Final[dict[str, str]] = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{BASE_URL}/messaging",
    "Origin": BASE_URL,
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua": (
        f'"Chromium";v="{CHROME_VERSION}", "Not(A:Brand";v="24", '
        f'"Google Chrome";v="{CHROME_VERSION}"'
    ),
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# Config entry data key -> browser cookie name
COOKIE_KEYS: Final[dict[str, str]] = {
    "connect_sid": "connect.sid",
    "csrf": "_csrf",
    "xsrf_token": "XSRF-TOKEN",
}

REQUEST_TIMEOUT: Final = aiohttp.ClientTimeout(
    total=45, connect=15, sock_connect=15, sock_read=30
)
UPLOAD_TIMEOUT: Final = aiohttp.ClientTimeout(total=180, connect=15, sock_connect=15)

MAX_ATTEMPTS: Final = 3
RETRY_DELAY: Final = 2.0
AUTH_STATUSES: Final = frozenset({401, 419})
RETRY_STATUSES: Final = frozenset({408, 425, 429, 500, 502, 503, 504})

# Markers PerimeterX puts in its block pages.
BOT_BLOCK_MARKERS: Final = (
    "perimeterx",
    "px-captcha",
    "_pxhd",
    "access to this page has been denied",
)

# Session cookies rotate on almost every call, so only write the refreshed
# values to the config entry occasionally unless the login cookie itself moved.
COOKIE_PERSIST_INTERVAL: Final = timedelta(minutes=15)


class TextNowError(HomeAssistantError):
    """Base class for TextNow API problems."""


class TextNowAuthError(TextNowError):
    """Raised when TextNow no longer accepts the stored browser session."""


class TextNowBlockedError(TextNowAuthError):
    """Raised when TextNow's bot protection blocks the request."""

    issue_key = "bot_blocked"


class TextNowConnectionError(TextNowError):
    """Raised when TextNow cannot be reached."""


class TextNowApiError(TextNowError):
    """Raised when TextNow answers with something unexpected."""


def cookies_from_entry_data(data: dict[str, Any]) -> dict[str, str]:
    """Return the cookies to replay for a stored account.

    Everything the user pasted is replayed, not just the session cookies:
    the bot protection cookies are part of what makes a request look like
    the browser the session was created in.
    """
    cookies = {
        str(name): str(value)
        for name, value in (data.get(CONF_COOKIES) or {}).items()
        if value
    }
    # Accounts set up before the full cookie bag was stored
    for key, name in COOKIE_KEYS.items():
        if data.get(key) and name not in cookies:
            cookies[name] = str(data[key])
    # An entry saved by an older release may hold wreckage from a bad paste,
    # which would otherwise break every request rather than just setup.
    return sanitize_cookies(cookies)


def _cookie_is_expired(morsel: Morsel) -> bool:
    """Return whether a Set-Cookie is really a delete.

    A server signals a logout either with max-age=0 or with an expires date
    in the past. Reading only max-age meant an expires-style logout was
    absorbed and replayed as though it were a fresh cookie.
    """
    max_age = str(morsel.get("max-age", "")).strip()
    if max_age:
        try:
            return int(max_age) <= 0
        except ValueError:
            return False

    expires = str(morsel.get("expires", "")).strip()
    if not expires:
        return False
    when = dt_util.parse_datetime(expires) or _parse_http_date(expires)
    return when is not None and when <= dt_util.utcnow()


def _parse_http_date(value: str) -> datetime | None:
    """Return an RFC 1123 cookie date, the format servers actually send."""
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def csrf_token(cookies: dict[str, str]) -> str:
    """Return the value TextNow expects in the X-CSRF-Token header.

    The XSRF-TOKEN cookie holds the plain token. When it is missing the token
    has to be recovered from the URL encoded _csrf cookie.
    """
    xsrf = str(cookies.get("XSRF-TOKEN") or "")
    if xsrf:
        return xsrf
    csrf = str(cookies.get("_csrf") or "")
    if csrf.startswith("s%3A"):
        return unquote(csrf)
    return csrf


def build_headers(
    cookies: dict[str, str], extra: dict[str, str] | None = None
) -> dict[str, str]:
    """Return the headers a TextNow web session sends on every call.

    The cookies go in as a header rather than through aiohttp's cookies=
    argument. aiohttp hands those to http.cookies.SimpleCookie, which raises
    CookieError on a name it dislikes -- an exception that is neither a
    ClientError nor a HomeAssistantError, so it escapes every handler here
    and surfaces as "unexpected error" with a traceback.
    """
    headers = {**BROWSER_HEADERS, "X-CSRF-Token": csrf_token(cookies)}
    header = cookie_header(cookies)
    if header:
        headers["Cookie"] = header
    if extra:
        headers.update(extra)
    return headers


def _is_bot_block(body: str) -> bool:
    """Return whether a refusal came from PerimeterX rather than TextNow."""
    lowered = body.lower()
    return any(marker in lowered for marker in BOT_BLOCK_MARKERS)


def _raise_for_auth_status(status: int, body: str) -> None:
    """Raise the error that matches a rejected request.

    A 401 is an expired session. A 403 is either the same thing or the bot
    protection stepping in; both need fresh cookies but the advice differs.
    """
    if status == 403:
        if _is_bot_block(body):
            raise TextNowBlockedError(
                "TextNow's bot protection blocked Home Assistant (HTTP 403). "
                "Fresh cookies from a browser session are needed"
            )
        raise TextNowAuthError(
            "TextNow refused the request (HTTP 403); the saved cookies are "
            "no longer valid"
        )
    raise TextNowAuthError(
        f"TextNow rejected the session (HTTP {status}); the saved cookies are "
        "no longer valid"
    )


def _parse_json_body(body: str) -> Any:
    """Return the decoded API payload.

    An expired session makes TextNow answer with the sign-in page instead of
    JSON, which has to be reported as an authentication problem.
    """
    stripped = body.lstrip()
    if not stripped:
        return {}
    if stripped.startswith("<"):
        raise TextNowAuthError(
            "TextNow returned a web page instead of API data, "
            "which means the browser session has expired"
        )
    try:
        return json.loads(stripped)
    except ValueError as err:
        raise TextNowApiError(
            f"Could not read the TextNow response: {stripped[:200]}"
        ) from err


async def async_api_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    headers_factory: Callable[[], dict[str, str]],
    cookie_sink: Callable[[SimpleCookie], None] | None = None,
    params: dict[str, str] | None = None,
    json_data: Any = None,
    data: Any = None,
    timeout: aiohttp.ClientTimeout = REQUEST_TIMEOUT,
    parse_json: bool = True,
    attempts: int = MAX_ATTEMPTS,
    check_auth: bool = True,
) -> Any:
    """Call the TextNow API and retry the failures worth retrying.

    Headers, including the Cookie header, are rebuilt for every attempt, and
    the cookies TextNow sends back are handed to the caller, so a rotated
    session is followed instead of replaying the values the session started
    with.
    """
    last_error = "no attempt was made"

    for attempt in range(1, attempts + 1):
        try:
            async with session.request(
                method,
                url,
                params=params,
                json=json_data,
                data=data,
                headers=headers_factory(),
                timeout=timeout,
            ) as response:
                # Read the new cookies first: a rejected request still
                # carries the values the next attempt should use.
                if cookie_sink is not None and response.cookies:
                    cookie_sink(response.cookies)

                if check_auth and (
                    response.status in AUTH_STATUSES or response.status == 403
                ):
                    body = await response.text()
                    # A 403 that is not the bot protection is usually the CSRF
                    # token and the cookie disagreeing. The refreshed token
                    # arrived with this very reply and has just been absorbed,
                    # so one more attempt settles it rather than demanding a
                    # whole new sign-in.
                    if (
                        response.status != 403
                        or attempt >= attempts
                        or _is_bot_block(body)
                    ):
                        _raise_for_auth_status(response.status, body)
                    last_error = "HTTP 403 (CSRF token refreshed, retrying)"
                elif response.status not in RETRY_STATUSES:
                    if response.status >= 400:
                        body = await response.text()
                        raise TextNowApiError(
                            f"TextNow returned HTTP {response.status}: {body[:200]}"
                        )
                    if not parse_json:
                        return await response.read()
                    return _parse_json_body(await response.text())
                else:
                    last_error = f"HTTP {response.status}"
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            last_error = f"{type(err).__name__}: {err}"

        if attempt < attempts:
            delay = RETRY_DELAY * attempt
            _LOGGER.debug(
                "TextNow request %s %s failed (%s), retrying in %s s",
                method,
                url,
                last_error,
                delay,
            )
            await asyncio.sleep(delay)

    raise TextNowConnectionError(
        f"TextNow did not answer after {attempts} attempts: {last_error}"
    )


@callback
def _async_release_session(session: aiohttp.ClientSession | None) -> None:
    """Give up a session created with auto_cleanup disabled.

    The connector belongs to Home Assistant and is shared with every other
    integration, so the session is detached rather than closed. Home Assistant
    also replaces close() on the sessions it hands out with a shim that only
    logs "this integration closes the Home Assistant aiohttp session" and asks
    the user to file a bug report, so calling it would warn and still leak.
    """
    if session is not None and not session.closed:
        session.detach()


async def async_validate_session(
    hass: HomeAssistant, username: str, cookies: dict[str, str]
) -> None:
    """Check a username and cookie set against the TextNow API.

    Raises TextNowAuthError, TextNowConnectionError or TextNowApiError.
    """
    session = async_create_clientsession(
        hass,
        auto_cleanup=False,
        cookie_jar=aiohttp.DummyCookieJar(),
        timeout=REQUEST_TIMEOUT,
    )
    try:
        await async_api_request(
            session,
            "GET",
            f"{BASE_URL}/api/users/{username}/messages",
            headers_factory=lambda: build_headers(cookies),
            params={
                "start_message_id": "0",
                "direction": "future",
                "page_size": "1",
            },
            attempts=2,
        )
    finally:
        _async_release_session(session)


class TextNowDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching TextNow data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.entry = entry
        self.storage = TextNowStorage(hass, entry.entry_id)
        self.session: aiohttp.ClientSession | None = None
        self.auth_failed = False
        self.last_success: datetime | None = None
        self._config: dict[str, Any] = dict(entry.data)
        self._cookies: dict[str, str] = cookies_from_entry_data(entry.data)
        self._last_cookie_write: datetime | None = None
        self._cookies_unsaved = False
        self._failures = 0
        self._last_outbound: datetime | None = None
        self._last_outbound_read = False
        self._keepalive_checked: datetime | None = None
        self._keepalive_task: asyncio.Task[bool] | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=self.polling_interval),
        )

    @property
    def username(self) -> str:
        """Return the TextNow username this entry talks to."""
        return str(self._config.get(CONF_USERNAME, ""))

    @property
    def polling_interval(self) -> int:
        """Return the configured polling interval in seconds."""
        try:
            interval = int(
                self._config.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)
            )
        except (TypeError, ValueError):
            interval = DEFAULT_POLLING_INTERVAL
        return max(MIN_POLLING_INTERVAL, interval)

    @property
    def keepalive_phone(self) -> str:
        """Return the number the keep-alive texts, or "" when it is off."""
        return str(self._config.get(CONF_KEEPALIVE_PHONE) or "")

    @property
    def keepalive_days(self) -> int:
        """Return how many idle days may pass before a keep-alive is sent."""
        try:
            days = int(self._config.get(CONF_KEEPALIVE_DAYS) or DEFAULT_KEEPALIVE_DAYS)
        except (TypeError, ValueError):
            days = DEFAULT_KEEPALIVE_DAYS
        return min(MAX_KEEPALIVE_DAYS, max(MIN_KEEPALIVE_DAYS, days))

    @property
    def keepalive_message(self) -> str:
        """Return the text the keep-alive sends."""
        return (
            str(self._config.get(CONF_KEEPALIVE_MESSAGE) or "").strip()
            or DEFAULT_KEEPALIVE_MESSAGE
        )

    @property
    def last_outbound(self) -> datetime | None:
        """Return when this account last sent anything."""
        return self._last_outbound

    @property
    def keepalive_due_at(self) -> datetime | None:
        """Return when the next keep-alive would be sent, if it is on."""
        if not self.keepalive_phone or self._last_outbound is None:
            return None
        return self._last_outbound + timedelta(days=self.keepalive_days)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from TextNow."""
        try:
            await self._poll_unread_messages()
            await self._cleanup_expired_pending()
        except TextNowAuthError as err:
            self._async_slow_to_recovery_polling()
            self._async_report_auth_problem(err)
            raise ConfigEntryAuthFailed(str(err)) from err
        except TextNowError as err:
            self._async_back_off()
            raise UpdateFailed(str(err)) from err

        self._async_resume_normal_polling()
        self._async_schedule_keepalive()
        return {}

    @callback
    def _async_schedule_keepalive(self) -> None:
        """Check the keep-alive without holding up the poll.

        Sending is a round trip to TextNow, and this runs off the back of
        every poll, including the one that sets the entry up.
        """
        if not self.keepalive_phone:
            return
        if self._keepalive_task is not None and not self._keepalive_task.done():
            return
        if (
            self._keepalive_checked is not None
            and dt_util.utcnow() - self._keepalive_checked < KEEPALIVE_RETRY_INTERVAL
        ):
            return
        self._keepalive_task = self.entry.async_create_background_task(
            self.hass, self.async_run_keepalive(), name="textnow keep-alive"
        )

    async def async_note_outbound_use(self) -> None:
        """Record that the number was just used to send something.

        Anything the user sends counts, so a house that texts every day never
        triggers a keep-alive of its own.
        """
        self._last_outbound = dt_util.utcnow()
        self._last_outbound_read = True
        await self.storage.async_set_last_outbound(self._last_outbound.isoformat())

    async def async_run_keepalive(self, *, force: bool = False) -> bool:
        """Text the safe number if nothing has been sent for long enough.

        TextNow gives an idle number back to the pool, which costs the user
        their number and every automation pointed at it. Returns True when a
        message was sent.
        """
        phone = self.keepalive_phone
        if not phone:
            return False

        now = dt_util.utcnow()
        if (
            not force
            and self._keepalive_checked is not None
            and now - self._keepalive_checked < KEEPALIVE_RETRY_INTERVAL
        ):
            return False
        self._keepalive_checked = now

        if not self._last_outbound_read:
            stored = await self.storage.async_get_last_outbound()
            self._last_outbound = dt_util.parse_datetime(stored) if stored else None
            self._last_outbound_read = True

        # With nothing recorded there is no way to tell how long the number has
        # been idle, so one message goes out now and starts the clock.
        idle_for = None if self._last_outbound is None else now - self._last_outbound
        if not force and idle_for is not None:
            if idle_for < timedelta(days=self.keepalive_days):
                return False

        try:
            await self.send_message(phone, self.keepalive_message)
        except HomeAssistantError as err:
            # Retried on the next hourly check; the session problems that cause
            # this already report themselves through the entry state.
            _LOGGER.warning("Could not send the TextNow keep-alive message: %s", err)
            return False

        _LOGGER.info(
            "Sent a TextNow keep-alive message after %s idle days",
            "unknown" if idle_for is None else idle_for.days,
        )
        return True

    async def async_shutdown(self) -> None:
        """Release the session on shutdown."""
        await super().async_shutdown()
        # Cookies held back by the write throttle would otherwise be lost, and
        # the next start would replay a set older than the one this session was
        # using by the time it stopped.
        if self._cookies_unsaved and self.hass.config_entries.async_get_entry(
            self.entry.entry_id
        ):
            self._async_persist_cookies(force=True)
        _async_release_session(self.session)
        self.session = None

    @callback
    def _async_slow_to_recovery_polling(self) -> None:
        """Back right off, but keep checking, after TextNow rejects a session.

        Setting update_interval to None here used to deadlock the account:
        auth_failed is only cleared by a poll, and with no interval there was
        never another poll, so the flag stayed true until Home Assistant
        restarted. Slowing down instead means a session that starts working
        again is noticed, and a dismissed reauth prompt comes back.
        """
        self.auth_failed = True
        if self.update_interval != AUTH_RECOVERY_INTERVAL:
            self.update_interval = AUTH_RECOVERY_INTERVAL
            _LOGGER.debug(
                "TextNow polling slowed to every %s minutes until the session "
                "is renewed",
                int(AUTH_RECOVERY_INTERVAL.total_seconds() // 60),
            )

    @callback
    def async_rearm_polling(self) -> None:
        """Return to the configured interval and retry straight away.

        Called when something outside the poll loop may have fixed the
        session, such as the panel's refresh button.
        """
        self.auth_failed = False
        self._failures = 0
        interval = timedelta(seconds=self.polling_interval)
        if self.update_interval != interval:
            self.update_interval = interval

    @callback
    def _async_back_off(self) -> None:
        """Slow polling down while TextNow keeps failing."""
        self.auth_failed = False
        self._failures += 1
        backoff = min(
            self.polling_interval * 2**self._failures,
            int(MAX_BACKOFF_INTERVAL.total_seconds()),
        )
        interval = timedelta(seconds=backoff)
        if self.update_interval != interval:
            self.update_interval = interval
            _LOGGER.debug(
                "TextNow polling backed off to %s s after %s failures",
                backoff,
                self._failures,
            )

    @callback
    def _async_resume_normal_polling(self) -> None:
        """Restore the configured interval after a successful poll."""
        self.auth_failed = False
        self._failures = 0
        self.last_success = dt_util.utcnow()
        interval = timedelta(seconds=self.polling_interval)
        if self.update_interval != interval:
            self.update_interval = interval
        self._async_clear_auth_problem()

    @callback
    def _async_report_auth_problem(self, err: TextNowAuthError) -> None:
        """Raise a repair item when Home Assistant's own is not enough.

        Asking for a reauth already puts "Authentication expired" in Repairs
        with a button that opens the form, so repeating it here would be two
        cards for one problem. Being turned away by the bot protection needs
        different steps, which is worth its own card.
        """
        if not isinstance(err, TextNowBlockedError):
            return

        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._auth_issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=err.issue_key,
            translation_placeholders={
                "account": self.entry.title or self.username,
            },
            learn_more_url=COOKIE_HELP_URL,
        )

    @callback
    def _async_clear_auth_problem(self) -> None:
        """Remove the repair item once the session works again."""
        ir.async_delete_issue(self.hass, DOMAIN, self._auth_issue_id)

    @property
    def _auth_issue_id(self) -> str:
        """Return the repair issue id for this account."""
        return f"bot_blocked_{self.entry.entry_id}"

    @callback
    def _async_get_session(self) -> aiohttp.ClientSession:
        """Return the session, creating it when needed.

        Cookies are passed per request and the Set-Cookie replies are tracked
        by hand. aiohttp's jar keeps a host scoped cookie alongside the
        Domain=.textnow.com one the server sends back and then replays the
        stale value, which is exactly how a live session gets lost.
        """
        if self.session is None or self.session.closed:
            self.session = async_create_clientsession(
                self.hass,
                auto_cleanup=False,
                cookie_jar=aiohttp.DummyCookieJar(),
                timeout=REQUEST_TIMEOUT,
            )
        return self.session

    @callback
    def _async_absorb_cookies(self, cookies: SimpleCookie) -> None:
        """Follow the cookies TextNow rotates during a session."""
        changed = False

        for name, morsel in cookies.items():
            value = morsel.value
            if _cookie_is_expired(morsel) or not value:
                if self._cookies.pop(name, None) is not None:
                    changed = True
                continue
            if not is_valid_cookie_name(name) or not is_valid_cookie_value(value):
                _LOGGER.debug("Ignoring unusable cookie %r sent by TextNow", name)
                continue
            if self._cookies.get(name) != value:
                self._cookies[name] = value
                changed = True

        # A rotated _csrf with no matching XSRF-TOKEN would leave the header
        # and the cookie disagreeing, which TextNow reads as a forged request.
        if changed and "_csrf" in cookies and "XSRF-TOKEN" not in cookies:
            refreshed = csrf_token(self._cookies)
            if refreshed and self._cookies.get("XSRF-TOKEN") not in (None, refreshed):
                self._cookies.pop("XSRF-TOKEN", None)
                _LOGGER.debug("Dropped the stale XSRF-TOKEN after _csrf rotated")

        if changed:
            self._async_persist_cookies()

    @callback
    def _async_persist_cookies(self, force: bool = False) -> None:
        """Store rotated cookies so a restart stays signed in.

        Everything the session authenticates with -- the login cookie and both
        CSRF cookies -- is written the moment it moves, because a saved set
        whose token no longer matches its session reads server side as a forged
        request. Only the noisy remainder, mostly bot protection cookies that
        rotate on every single call, is throttled to spare the disk, and that
        is flushed on shutdown so a restart inside the throttle window cannot
        resurrect a stale set.
        """
        now = dt_util.utcnow()
        stored = self.entry.data
        auth_cookies_moved = any(
            self._cookies.get(name, "") != str(stored.get(key) or "")
            for key, name in COOKIE_KEYS.items()
        )

        if (
            not force
            and not auth_cookies_moved
            and self._last_cookie_write is not None
            and now - self._last_cookie_write < COOKIE_PERSIST_INTERVAL
        ):
            self._cookies_unsaved = True
            return

        self._last_cookie_write = now
        self._cookies_unsaved = False
        data = {
            **self.entry.data,
            CONF_COOKIES: dict(self._cookies),
            **{
                key: self._cookies.get(name, "")
                for key, name in COOKIE_KEYS.items()
            },
        }
        self.hass.config_entries.async_update_entry(self.entry, data=data)
        _LOGGER.debug("Saved refreshed TextNow session cookies")

    def _headers_factory(
        self, extra: dict[str, str] | None = None
    ) -> Callable[[], dict[str, str]]:
        """Return a callable building headers from the live cookies."""

        def _factory() -> dict[str, str]:
            return build_headers(self._cookies, extra)

        return _factory

    async def _async_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_data: Any = None,
        data: Any = None,
        extra_headers: dict[str, str] | None = None,
        timeout: aiohttp.ClientTimeout = REQUEST_TIMEOUT,
        parse_json: bool = True,
    ) -> Any:
        """Run an authenticated request against the TextNow API."""
        session = self._async_get_session()
        try:
            return await async_api_request(
                session,
                method,
                url,
                headers_factory=self._headers_factory(extra_headers),
                cookie_sink=self._async_absorb_cookies,
                params=params,
                json_data=json_data,
                data=data,
                timeout=timeout,
                parse_json=parse_json,
            )
        except TextNowAuthError as err:
            # A service call has no coordinator refresh to report through, so
            # the reauth flow and the repair item are started here.
            if self.entry.state is ConfigEntryState.LOADED:
                self._async_slow_to_recovery_polling()
                self._async_report_auth_problem(err)
                self.entry.async_start_reauth(self.hass)
            raise

    async def _async_upload_attachment(
        self, upload_url: str, file_data: bytes, content_type: str
    ) -> None:
        """Upload a file to the pre-signed attachment URL.

        The upload host is not TextNow, so no session headers are sent and a
        403 from it means the pre-signed URL went stale, not that the TextNow
        session expired.
        """
        session = self._async_get_session()
        await async_api_request(
            session,
            "PUT",
            upload_url,
            headers_factory=lambda: {
                "Content-Type": content_type,
                "User-Agent": USER_AGENT,
            },
            data=file_data,
            timeout=UPLOAD_TIMEOUT,
            parse_json=False,
            check_auth=False,
        )

    async def _async_get_upload_url(self, message_type: str) -> str:
        """Request a pre-signed upload URL for an attachment."""
        payload = await self._async_request(
            "GET",
            f"{BASE_URL}/api/v3/attachment_url",
            params={"message_type": message_type},
        )
        upload_url = payload.get("result") if isinstance(payload, dict) else None
        if not upload_url:
            raise TextNowApiError("TextNow did not return an upload URL")
        return str(upload_url)

    async def _async_send_attachment(self, send_data: dict[str, str]) -> None:
        """Post an uploaded attachment to a contact."""
        await self._async_request(
            "POST",
            f"{BASE_URL}/api/v3/send_attachment",
            data=send_data,
            extra_headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=UPLOAD_TIMEOUT,
        )

    async def _poll_unread_messages(self) -> None:
        """Poll for new incoming messages."""
        if not self.username:
            raise TextNowApiError("No TextNow username is configured")

        payload = await self._async_request(
            "GET",
            f"{BASE_URL}/api/users/{self.username}/messages",
            params={
                "start_message_id": "0",
                "direction": "future",
                "page_size": "0",
            },
        )

        messages = _extract_messages(payload)
        if not messages:
            return

        data = await self.storage.async_load()
        processed = data.get("processed_message_ids") or set()
        contacts = data.get("contacts", {})
        # A fresh account adopts the existing history quietly, otherwise
        # setting up the integration would replay old texts into automations.
        history_adopted = bool(data.get("history_adopted")) or bool(processed)
        allowed_phones = self._config.get("allowed_phones") or []
        phone_to_contact = {
            contact["phone"]: contact_id
            for contact_id, contact in contacts.items()
            if contact.get("phone")
        }

        new_message_ids: list[str] = []

        for message in messages:
            # Message structure: id, contact_value, message, message_direction
            # (1 = incoming, 2 = outgoing)
            message_id = str(message.get("id", ""))
            if not message_id or message_id in processed:
                continue
            if message.get("message_direction") != 1:
                continue

            phone = message.get("contact_value", "")
            if not phone:
                continue

            new_message_ids.append(message_id)
            if not history_adopted:
                continue

            # Security: check allowed phones
            if allowed_phones and phone not in allowed_phones:
                _LOGGER.warning("Received message from unauthorized phone: %s", phone)
                continue

            text = message.get("message", "")
            timestamp = (
                message.get("timestamp")
                or message.get("date")
                or dt_util.utcnow().isoformat()
            )

            contact_id = phone_to_contact.get(phone, phone)
            contact_name = ""
            if contact_id in contacts:
                contact_name = contacts[contact_id].get("name", "")

            # Recorded here rather than in the device trigger so that
            # "reply to sender" also works for YAML triggers and for
            # automations that listen for the event directly.
            self.hass.data.setdefault(DOMAIN, {})["last_trigger_contact"] = {
                "contact_id": contact_id,
                "contact_name": contact_name,
                "phone": phone,
                "entity_id": f"sensor.textnow_{contact_id}" if contact_id else "",
            }

            self.hass.bus.async_fire(
                EVENT_MESSAGE_RECEIVED,
                {
                    ATTR_PHONE: phone,
                    ATTR_TEXT: text,
                    ATTR_MESSAGE_ID: message_id,
                    ATTR_TIMESTAMP: timestamp,
                    ATTR_CONTACT_ID: contact_id,
                    "contact_name": contact_name,
                },
            )

            await self._check_pending_expectations(phone, text, contact_id)

        if new_message_ids or not history_adopted:
            if not history_adopted:
                _LOGGER.debug(
                    "Adopted %s existing TextNow messages without firing events",
                    len(new_message_ids),
                )
            # One write per poll instead of one per message.
            await self.storage.async_mark_messages_processed(new_message_ids)

    async def _check_pending_expectations(
        self, phone: str, text: str, contact_id: str
    ) -> None:
        """Check if message matches any pending expectations."""
        pending = await self.storage.async_get_pending(phone)
        if not pending:
            return

        for key, pending_data in list(pending.items()):
            prompt_type = pending_data.get("type", "text")
            options = pending_data.get("options")
            regex = pending_data.get("regex")

            parsed = parse_reply(text, prompt_type, options, regex)
            if parsed:
                # Get response value (option number for choice type)
                if parsed.get("option_index") is not None:
                    response_value = str(parsed.get("option_index") + 1)  # 1, 2, 3, etc.
                else:
                    response_value = str(parsed["value"])

                # Fire reply parsed event with response_variable name if specified
                event_data = {
                    ATTR_PHONE: phone,
                    ATTR_CONTACT_ID: contact_id,
                    ATTR_TYPE: parsed["type"],
                    ATTR_VALUE: parsed["value"],
                    ATTR_RAW_TEXT: parsed["raw_text"],
                    ATTR_OPTION_INDEX: parsed.get("option_index"),
                    "response_number": response_value,  # The option number (1, 2, 3, etc.)
                }

                # Include response_variable name in event if specified
                response_variable = pending_data.get("response_variable")
                if response_variable:
                    event_data["response_variable"] = response_variable

                self.hass.bus.async_fire(EVENT_REPLY_PARSED, event_data)

                # Always clear pending after first match (removed keep_pending feature)
                await self.storage.async_clear_pending(phone, key)

                # Only process first match (one pending per phone)
                break

    async def _cleanup_expired_pending(self) -> None:
        """Clean up expired pending expectations."""
        data = await self.storage.async_load()
        pending = data.get("pending", {})
        now = dt_util.utcnow()

        for phone, phone_pending in list(pending.items()):
            for key, pending_data in list(phone_pending.items()):
                created_at = pending_data.get("created_at")
                ttl_seconds = pending_data.get("ttl_seconds", 300)

                if created_at:
                    try:
                        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        if now - created_dt > timedelta(seconds=ttl_seconds):
                            await self.storage.async_clear_pending(phone, key)
                            _LOGGER.debug("Cleared expired pending: %s/%s", phone, key)
                    except (ValueError, TypeError):
                        pass

    async def send_message(self, phone: str, message: str) -> None:
        """Send an SMS message."""
        # POST /api/users/{username}/messages
        # JSON: {"contact_value": "phone", "message_direction": 2, "contact_type": 2, "message": "text"}
        await self._async_request(
            "POST",
            f"{BASE_URL}/api/users/{self.username}/messages",
            json_data={
                "contact_value": phone,
                "message_direction": 2,  # 2 = outgoing
                "contact_type": 2,  # 2 = phone number
                "message": message,
            },
        )
        await self.async_note_outbound_use()
        _LOGGER.debug("Message sent successfully to %s", phone)

    async def send_mms(
        self, phone: str, message: str, file_data: bytes, filename: str = "image.jpg"
    ) -> None:
        """Send an MMS message with image/media attachment.

        Uses 3-step API process:
        1. GET upload URL from /api/v3/attachment_url?message_type=2
        2. PUT file to pre-signed URL
        3. POST to /api/v3/send_attachment with form data

        Args:
            phone: Phone number to send to
            message: Caption text (optional)
            file_data: File data as bytes
            filename: Filename for content type detection (default: "image.jpg")
        """
        # Determine content type from file extension
        filename_lower = filename.lower()
        if filename_lower.endswith('.png'):
            content_type = 'image/png'
        elif filename_lower.endswith('.gif'):
            content_type = 'image/gif'
        else:
            content_type = 'image/jpeg'  # default for images

        upload_url = await self._async_get_upload_url("2")
        await self._async_upload_attachment(upload_url, file_data, content_type)
        await self._async_send_attachment(
            {
                "contact_value": phone,
                "contact_type": "2",
                "attachment_url": upload_url,
                "message_type": "2",
                "media_type": "images",
                "message": message,
            }
        )

        await self.async_note_outbound_use()
        _LOGGER.debug("MMS sent successfully to %s", phone)

    async def send_voice_message(self, phone: str, file_data: bytes) -> None:
        """Send a voice message with audio file.

        Uses 3-step API process:
        1. GET upload URL from /api/v3/attachment_url?message_type=3
        2. PUT audio file to pre-signed URL
        3. POST to /api/v3/send_attachment with form data

        Args:
            phone: Phone number to send to
            file_data: Audio file data as bytes
        """
        upload_url = await self._async_get_upload_url("3")
        await self._async_upload_attachment(upload_url, file_data, "audio/mpeg")
        await self._async_send_attachment(
            {
                "contact_value": phone,
                "contact_type": "2",
                "attachment_url": upload_url,
                "message_type": "3",
                "media_type": "audio",
                "message": "",  # Always empty for voice messages
            }
        )

        await self.async_note_outbound_use()
        _LOGGER.debug("Voice message sent successfully to %s", phone)


def _extract_messages(payload: Any) -> list[dict[str, Any]]:
    """Return the message list from the API payload.

    The API returns either a bare list or a wrapper object.
    """
    if isinstance(payload, list):
        return [message for message in payload if isinstance(message, dict)]
    if isinstance(payload, dict):
        for key in ("messages", "data", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [message for message in value if isinstance(message, dict)]
    return []
