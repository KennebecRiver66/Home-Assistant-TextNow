"""Config flow for TextNow integration."""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import unquote

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_COOKIES,
    CONF_POLLING_INTERVAL,
    CONF_USERNAME,
    COOKIE_HELP_URL,
    DEFAULT_POLLING_INTERVAL,
    MAX_POLLING_INTERVAL,
    MIN_POLLING_INTERVAL,
)
from .coordinator import (
    BASE_URL,
    COOKIE_KEYS,
    TextNowApiError,
    TextNowAuthError,
    TextNowConnectionError,
    async_validate_session,
)
from .storage import TextNowStorage
from .phone_utils import format_phone_number, readable_phone_number

_LOGGER = logging.getLogger(__name__)

# Cookie attributes that show up when a Set-Cookie header or a cookie
# manager export is pasted instead of a plain cookie line.
COOKIE_ATTRIBUTES = {
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

_CURL_COOKIE_PATTERN = re.compile(
    r"""(?:-H\s+['"]\s*cookie\s*:|-b\s+['"]|--cookie\s+['"])(?P<cookies>[^'"]+)['"]?""",
    re.IGNORECASE,
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
            key, _, value = part.partition("=")
            key = key.strip()
            value = value.strip()
            if not key or not value or key.lower() in COOKIE_ATTRIBUTES:
                continue
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            cookies[key] = value

    return cookies


def parse_cookie_string(cookie_string: str) -> dict[str, str]:
    """Return the cookies found in whatever the user pasted.

    Accepts a cookie header line, the output of document.cookie, a
    "Copy as cURL" command, the devtools cookie table and the JSON
    exports produced by cookie manager browser extensions.
    """
    if not cookie_string:
        return {}

    text = cookie_string.strip()

    cookies = _parse_json_cookies(text)
    if cookies:
        return cookies

    curl_match = _CURL_COOKIE_PATTERN.search(text)
    if curl_match:
        text = curl_match.group("cookies")

    return _parse_cookie_pairs(text)


def normalize_username(raw_username: str) -> str:
    """Return the bare TextNow username."""
    username = (raw_username or "").strip().strip("@")
    for suffix in ("@textnow.me", "@textnow.com"):
        if username.lower().endswith(suffix):
            username = username[: -len(suffix)]
    return username.strip()


# A request URL or a cURL command carries the account name, which saves the
# user a trip to the TextNow settings page.
_USERNAME_PATTERNS = (
    re.compile(r"/api(?:/v\d+)?/users/([^/?\s'\"]+)/"),
    re.compile(r"[\"']user_?name[\"']\s*:\s*[\"']([^\"']+)[\"']"),
)


def extract_username(text: str) -> str:
    """Return the username found in a pasted request, if any."""
    for pattern in _USERNAME_PATTERNS:
        match = pattern.search(text or "")
        if not match:
            continue
        candidate = normalize_username(unquote(match.group(1)))
        if candidate and candidate.lower() not in {"me", "self", "undefined"}:
            return candidate
    return ""


def form_placeholders(**extra: str) -> dict[str, str]:
    """Return the links used by the cookie instructions.

    Translation strings may not contain URLs, so they arrive as placeholders.
    """
    return {"help_url": COOKIE_HELP_URL, "textnow_url": BASE_URL, **extra}


def contact_schema() -> vol.Schema:
    """Return the schema used to add or edit a contact."""
    return vol.Schema(
        {
            vol.Required("name"): selector.TextSelector(),
            vol.Required("phone"): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEL)
            ),
        }
    )


def credentials_schema(*, include_polling_interval: bool = False) -> vol.Schema:
    """Return the schema used to ask for account credentials."""
    fields: dict[Any, Any] = {
        # Optional: the username is read from the paste when left blank.
        vol.Optional(CONF_USERNAME): selector.TextSelector(
            selector.TextSelectorConfig(autocomplete="username")
        ),
        vol.Required("cookie_string"): selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        ),
    }

    if include_polling_interval:
        fields[vol.Optional("polling_interval")] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=MIN_POLLING_INTERVAL,
                max=MAX_POLLING_INTERVAL,
                step=5,
                unit_of_measurement="seconds",
                mode=selector.NumberSelectorMode.BOX,
            )
        )

    return vol.Schema(fields)


async def async_validate_account(
    hass: HomeAssistant, username: str, cookie_string: str
) -> tuple[str, dict[str, Any], dict[str, str]]:
    """Check a username and cookie paste against TextNow.

    Returns the username used, the values to store on the config entry, and
    any error to show on the form.
    """
    cookies = parse_cookie_string(cookie_string)
    if not cookies:
        return username, {}, {"base": "no_cookies"}
    if "connect.sid" not in cookies:
        return username, {}, {"base": "connect_sid_missing"}
    if "_csrf" not in cookies and "XSRF-TOKEN" not in cookies:
        return username, {}, {"base": "csrf_missing"}

    if not username:
        username = extract_username(cookie_string)
        if not username:
            return username, {}, {"base": "username_required"}
        _LOGGER.debug("Read the TextNow username from the pasted request")

    credentials: dict[str, Any] = {
        key: cookies.get(name, "") for key, name in COOKIE_KEYS.items()
    }
    # The rest of the paste is kept too: the bot protection cookies are part
    # of what makes the requests look like the browser they came from.
    credentials[CONF_COOKIES] = cookies

    try:
        await async_validate_session(hass, username, cookies)
    except TextNowAuthError as err:
        _LOGGER.debug("TextNow rejected the credentials: %s", err)
        return username, credentials, {"base": "invalid_auth"}
    except TextNowConnectionError as err:
        _LOGGER.debug("Could not reach TextNow: %s", err)
        return username, credentials, {"base": "cannot_connect"}
    except TextNowApiError as err:
        _LOGGER.error("Unexpected answer from TextNow: %s", err)
        return username, credentials, {"base": "unexpected_response"}
    except Exception:  # noqa: BLE001 - surfaced to the user as "unknown"
        _LOGGER.exception("Unexpected error validating the TextNow account")
        return username, credentials, {"base": "unknown"}

    return username, credentials, {}


class TextNowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TextNow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username, credentials, errors = await async_validate_account(
                self.hass,
                normalize_username(user_input.get(CONF_USERNAME, "")),
                user_input.get("cookie_string", ""),
            )

            if not errors:
                await self.async_set_unique_id(username.lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=username,
                    data={
                        CONF_USERNAME: username,
                        **credentials,
                        CONF_POLLING_INTERVAL: DEFAULT_POLLING_INTERVAL,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                credentials_schema(), user_input or {}
            ),
            errors=errors,
            description_placeholders=form_placeholders(),
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle expired cookies."""
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh cookie string."""
        entry = self._reauth_entry
        if entry is None:
            return self.async_abort(reason="reauth_failed")

        errors: dict[str, str] = {}
        stored_username = str(entry.data.get(CONF_USERNAME, ""))

        if user_input is not None:
            username, credentials, errors = await async_validate_account(
                self.hass,
                normalize_username(user_input.get(CONF_USERNAME) or stored_username),
                user_input.get("cookie_string", ""),
            )

            if not errors:
                # Contacts live in this entry's own store, so refreshing the
                # cookies keeps every contact, sensor and automation intact.
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_USERNAME: username, **credentials},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                credentials_schema(),
                user_input or {CONF_USERNAME: stored_username},
            ),
            errors=errors,
            description_placeholders=form_placeholders(username=stored_username),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return TextNowOptionsFlowHandler()


class TextNowOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for TextNow."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self.contact_id: str | None = None
        self.action_type: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu.

        A menu is one click per choice, where a dropdown plus Submit was two.
        """
        return self.async_show_menu(
            step_id="init", menu_options=["account", "contacts"]
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage account settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username, credentials, errors = await async_validate_account(
                self.hass,
                normalize_username(
                    user_input.get(CONF_USERNAME)
                    or self.config_entry.data.get(CONF_USERNAME, "")
                ),
                user_input.get("cookie_string", ""),
            )

            if not errors:
                polling_interval = int(
                    user_input.get(CONF_POLLING_INTERVAL) or DEFAULT_POLLING_INTERVAL
                )
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=username,
                    data={
                        **self.config_entry.data,
                        CONF_USERNAME: username,
                        **credentials,
                        CONF_POLLING_INTERVAL: polling_interval,
                    },
                )
                # Pick up the new credentials and polling interval right away.
                self.hass.config_entries.async_schedule_reload(
                    self.config_entry.entry_id
                )
                return self.async_create_entry(title="", data={})

        suggested = user_input or {
            CONF_USERNAME: self.config_entry.data.get(CONF_USERNAME, ""),
            "cookie_string": self._reconstruct_cookie_string(),
            CONF_POLLING_INTERVAL: self.config_entry.data.get(
                CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
            ),
        }

        return self.async_show_form(
            step_id="account",
            data_schema=self.add_suggested_values_to_schema(
                credentials_schema(include_polling_interval=True), suggested
            ),
            errors=errors,
            description_placeholders=form_placeholders(),
        )

    def _reconstruct_cookie_string(self) -> str:
        """Rebuild the cookie line from the stored cookies for editing."""
        cookies = dict(self.config_entry.data.get(CONF_COOKIES) or {})
        for key, name in COOKIE_KEYS.items():
            if self.config_entry.data.get(key):
                cookies[name] = self.config_entry.data[key]
        return "; ".join(f"{name}={value}" for name, value in cookies.items())

    async def async_step_contacts(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage contacts."""
        storage = TextNowStorage(self.hass, self.config_entry.entry_id)
        contacts = await storage.async_get_contacts()

        if contacts:
            contacts_text = "\n".join(
                f"- {data.get('name', 'Unknown')} "
                f"({readable_phone_number(data.get('phone', ''))})"
                for data in contacts.values()
            )
        else:
            contacts_text = "No contacts yet."

        menu_options = ["add_contact"]
        if contacts:
            menu_options += ["pick_edit", "pick_delete"]
        menu_options.append("init")

        return self.async_show_menu(
            step_id="contacts",
            menu_options=menu_options,
            description_placeholders={"contacts": contacts_text},
        )

    async def async_step_pick_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a contact to edit."""
        self.action_type = "edit"
        return await self.async_step_select_contact()

    async def async_step_pick_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a contact to remove."""
        self.action_type = "delete"
        return await self.async_step_select_contact()

    async def async_step_add_contact(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a new contact."""
        errors: dict[str, str] = {}
        formatted_phone = ""

        if user_input is not None:
            try:
                formatted_phone = format_phone_number(user_input["phone"])
            except ValueError:
                errors["phone"] = "invalid_phone"

        if user_input is None or errors:
            return self.async_show_form(
                step_id="add_contact",
                data_schema=self.add_suggested_values_to_schema(
                    contact_schema(), user_input or {}
                ),
                errors=errors,
            )

        storage = TextNowStorage(self.hass, self.config_entry.entry_id)
        contact_id = (
            f"contact_{user_input['name'].lower().replace(' ', '_')}"
        )

        contacts = await storage.async_get_contacts()
        counter = 1
        original_id = contact_id
        while contact_id in contacts:
            contact_id = f"{original_id}_{counter}"
            counter += 1

        await storage.async_save_contact(
            contact_id, user_input["name"], formatted_phone
        )

        # Fire event to add sensor
        self.hass.bus.async_fire(
            f"{DOMAIN}_contact_added",
            {
                "contact_id": contact_id,
                "name": user_input["name"],
                "phone": formatted_phone,
            },
        )

        return self.async_create_entry(title="", data={})

    async def async_step_select_contact(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a contact for edit or delete."""
        if not self.action_type:
            return await self.async_step_contacts()

        storage = TextNowStorage(self.hass, self.config_entry.entry_id)
        contacts = await storage.async_get_contacts()

        if not contacts:
            return self.async_abort(reason="no_contacts")

        if user_input is None:
            options = [
                selector.SelectOptionDict(
                    value=contact_id,
                    label=(
                        f"{data.get('name', 'Unknown')} "
                        f"({readable_phone_number(data.get('phone', ''))})"
                    ),
                )
                for contact_id, data in contacts.items()
            ]
            return self.async_show_form(
                step_id="select_contact",
                data_schema=vol.Schema(
                    {
                        vol.Required("contact_id"): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=options,
                                mode=selector.SelectSelectorMode.LIST,
                            )
                        ),
                    }
                ),
                description_placeholders={"action": self.action_type},
            )

        contact_id = user_input.get("contact_id")
        if not contact_id:
            return await self.async_step_contacts()

        self.contact_id = contact_id

        if self.action_type == "edit":
            return await self.async_step_edit_contact()
        if self.action_type == "delete":
            return await self.async_step_confirm_delete()
        return await self.async_step_contacts()

    async def async_step_confirm_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm contact deletion."""
        if not self.contact_id:
            return await self.async_step_contacts()

        storage = TextNowStorage(self.hass, self.config_entry.entry_id)
        contacts = await storage.async_get_contacts()

        if self.contact_id not in contacts:
            return self.async_abort(reason="contact_not_found")

        contact = contacts[self.contact_id]
        contact_name = contact.get("name", "Unknown")

        if user_input is None:
            return self.async_show_form(
                step_id="confirm_delete",
                data_schema=vol.Schema(
                    {
                        vol.Required("confirm"): bool,
                    }
                ),
                description_placeholders={"name": contact_name},
            )

        if user_input.get("confirm"):
            await storage.async_delete_contact(self.contact_id)
            self.hass.bus.async_fire(
                f"{DOMAIN}_contact_deleted",
                {"contact_id": self.contact_id},
            )
            return self.async_create_entry(title="", data={})

        return await self.async_step_contacts()

    async def async_step_edit_contact(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit a contact."""
        if not self.contact_id:
            return await self.async_step_contacts()

        storage = TextNowStorage(self.hass, self.config_entry.entry_id)
        contacts = await storage.async_get_contacts()

        if self.contact_id not in contacts:
            return self.async_abort(reason="contact_not_found")

        contact = contacts[self.contact_id]
        errors: dict[str, str] = {}
        formatted_phone = ""

        if user_input is not None:
            try:
                formatted_phone = format_phone_number(user_input["phone"])
            except ValueError:
                errors["phone"] = "invalid_phone"

        if user_input is None or errors:
            suggested = user_input or {
                "name": contact.get("name", ""),
                "phone": contact.get("phone", "").replace("+1", ""),
            }
            return self.async_show_form(
                step_id="edit_contact",
                data_schema=self.add_suggested_values_to_schema(
                    contact_schema(), suggested
                ),
                errors=errors,
                description_placeholders={"name": contact.get("name", "")},
            )

        await storage.async_save_contact(
            self.contact_id, user_input["name"], formatted_phone
        )

        return self.async_create_entry(title="", data={})
