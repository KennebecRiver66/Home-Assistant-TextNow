"""The notify platform, which is how an automation reaches TextNow generically.

Automations and blueprints written for other SMS integrations send a message, a
title, a target and a data dict, so what matters here is that each of those
arrives at the same send the textnow.send service performs. All numbers are in
the 555 range reserved for fiction.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
import voluptuous as vol
from homeassistant.components.notify import NotifyEntityFeature
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.textnow import services
from custom_components.textnow.const import DOMAIN
from custom_components.textnow.notify import TextNowNotifyEntity
from custom_components.textnow.services import (
    NOTIFY_SEND_SCHEMA,
    async_notify,
    notify_text,
)
from fakes import FakeHass

SAM = "+15555550101"
ALICE = "+15555550102"

CONTACTS: dict[str, dict[str, str]] = {
    "contact_sam": {"name": "Sam", "phone": SAM},
    "contact_alice": {"name": "Alice", "phone": ALICE},
}


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _Bus:
    """Records the events the send path fires."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def async_fire(self, event_type: str, event_data: dict[str, Any]) -> None:
        self.events.append((event_type, event_data))


class _Hass(FakeHass):
    """FakeHass plus the bus and the states the send path reads."""

    def __init__(self) -> None:
        super().__init__()
        self.bus = _Bus()
        self.states = SimpleNamespace(
            _states={}, get=lambda entity_id: self._state_map.get(entity_id)
        )
        self._state_map: dict[str, Any] = {}
        self.data[DOMAIN] = {}

    def set_contact_sensor(self, entity_id: str, phone: str) -> None:
        self._state_map[entity_id] = SimpleNamespace(attributes={"phone": phone})

    async def async_add_executor_job(self, target: Any, *args: Any) -> Any:
        """Reading an attachment goes to a thread; here it can just run."""
        return target(*args)


class _Storage:
    """The contact book, without a real Store behind it."""

    def __init__(self, hass: Any, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id

    async def async_get_contacts(self) -> dict[str, dict[str, str]]:
        return {contact_id: dict(c) for contact_id, c in CONTACTS.items()}


class _Account:
    """The coordinator's send methods, with a note of what went out."""

    username = "demo_account"
    last_update_success = False

    def __init__(self, hass: _Hass) -> None:
        self.hass = hass
        self.entry = hass.make_entry()
        self.sent: list[tuple[str, str]] = []
        self.mms: list[tuple[str, str, bytes, str]] = []
        self.voice: list[tuple[str, bytes]] = []
        self.dead_numbers: set[str] = set()

    async def send_message(self, phone: str, message: str) -> None:
        if phone in self.dead_numbers:
            raise HomeAssistantError(f"{phone} is not in service")
        self.sent.append((phone, message))

    async def send_mms(
        self, phone: str, message: str, file_data: bytes, filename: str = "image.jpg"
    ) -> None:
        self.mms.append((phone, message, file_data, filename))

    async def send_voice_message(self, phone: str, file_data: bytes) -> None:
        self.voice.append((phone, file_data))


@pytest.fixture(autouse=True)
def _fake_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every contact lookup in the send path goes through this module global."""
    monkeypatch.setattr(services, "TextNowStorage", _Storage)


@pytest.fixture
def account() -> _Account:
    return _Account(_Hass())


def _media_file(tmp_path: Any, name: str, payload: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(payload)
    return str(path)


def test_a_phone_number_target_is_dialled_the_way_textnow_wants_it(
    account: _Account,
) -> None:
    """However the number is written, TextNow gets +1XXXXXXXXXX."""
    _run(
        async_notify(
            account.hass, account, {"message": "hi", "target": ["(555) 555-0101"]}
        )
    )

    assert account.sent == [(SAM, "hi")]


def test_a_contact_can_be_targeted_by_name(account: _Account) -> None:
    """The name in the contact list is what an automation author will type."""
    _run(async_notify(account.hass, account, {"message": "hi", "target": ["sam"]}))

    assert account.sent == [(SAM, "hi")]


def test_a_contact_can_be_targeted_by_its_storage_id(account: _Account) -> None:
    _run(
        async_notify(
            account.hass, account, {"message": "hi", "target": ["contact_alice"]}
        )
    )

    assert account.sent == [(ALICE, "hi")]


def test_a_contact_can_be_targeted_by_its_sensor(account: _Account) -> None:
    """sensor.textnow_<name> is what the docs and the panel show."""
    account.hass.set_contact_sensor("sensor.textnow_sam", SAM)

    _run(
        async_notify(
            account.hass, account, {"message": "hi", "target": ["sensor.textnow_sam"]}
        )
    )

    assert account.sent == [(SAM, "hi")]


def test_a_title_becomes_the_first_line() -> None:
    """A text message has no title field, so dropping it would lose it."""
    assert notify_text("The door is open", "Alert") == "Alert\nThe door is open"
    assert notify_text("The door is open", None) == "The door is open"
    assert notify_text("The door is open", "   ") == "The door is open"
    assert notify_text("", "Alert") == "Alert"


def test_a_title_reaches_the_message_that_is_sent(account: _Account) -> None:
    _run(
        async_notify(
            account.hass,
            account,
            {"message": "The door is open", "title": "Alert", "target": ["Sam"]},
        )
    )

    assert account.sent == [(SAM, "Alert\nThe door is open")]


def test_every_target_is_tried_even_when_one_of_them_fails(
    account: _Account,
) -> None:
    """One disconnected number must not silence the notification for the rest."""
    account.dead_numbers = {SAM}

    with pytest.raises(HomeAssistantError):
        _run(
            async_notify(
                account.hass, account, {"message": "hi", "target": ["Sam", "Alice"]}
            )
        )

    assert account.sent == [(ALICE, "hi")]


def test_a_single_failing_target_reports_the_original_error(
    account: _Account,
) -> None:
    account.dead_numbers = {SAM}

    with pytest.raises(HomeAssistantError, match="not in service"):
        _run(async_notify(account.hass, account, {"message": "hi", "target": ["Sam"]}))

    assert account.sent == []


def test_an_unknown_target_names_the_contacts_that_do_exist(
    account: _Account,
) -> None:
    with pytest.raises(ServiceValidationError, match="contact_sam"):
        _run(async_notify(account.hass, account, {"message": "hi", "target": ["Bob"]}))


def test_an_empty_target_says_what_a_target_looks_like(account: _Account) -> None:
    with pytest.raises(ServiceValidationError, match="10-digit"):
        _run(async_notify(account.hass, account, {"message": "hi", "target": ["  "]}))


def test_no_target_replies_to_whoever_wrote_last(account: _Account) -> None:
    """The same fallback textnow.send has, so a reply blueprint works."""
    account.hass.data[DOMAIN]["last_trigger_contact"] = {"phone": SAM}

    _run(async_notify(account.hass, account, {"message": "on my way"}))

    assert account.sent == [(SAM, "on my way")]


def test_an_image_in_the_data_dict_is_sent_as_mms(
    account: _Account, tmp_path: Any
) -> None:
    path = _media_file(tmp_path, "photo.jpg", b"jpeg-bytes")

    _run(
        async_notify(
            account.hass,
            account,
            {"message": "look", "target": ["Sam"], "data": {"image": path}},
        )
    )

    assert account.sent == [(SAM, "look")]
    assert account.mms == [(SAM, "look", b"jpeg-bytes", "photo.jpg")]


def test_the_attachment_key_other_integrations_use_is_accepted(
    account: _Account, tmp_path: Any
) -> None:
    """Twilio calls it media_url, and sends a list of them."""
    path = _media_file(tmp_path, "photo.png", b"png-bytes")

    _run(
        async_notify(
            account.hass,
            account,
            {"message": "", "target": ["Sam"], "data": {"media_url": [path]}},
        )
    )

    assert account.sent == []
    assert account.mms == [(SAM, "", b"png-bytes", "photo.png")]


def test_audio_in_the_data_dict_is_sent_as_a_voice_message(
    account: _Account, tmp_path: Any
) -> None:
    path = _media_file(tmp_path, "clip.mp3", b"mp3-bytes")

    _run(
        async_notify(
            account.hass,
            account,
            {"message": "", "target": ["Sam"], "data": {"audio": path}},
        )
    )

    assert account.voice == [(SAM, b"mp3-bytes")]


def test_a_call_with_nothing_to_send_says_so(account: _Account) -> None:
    with pytest.raises(ServiceValidationError, match="Nothing to send"):
        _run(async_notify(account.hass, account, {"message": "", "target": ["Sam"]}))


def test_the_schema_is_home_assistants_notification_payload() -> None:
    """What every notify service accepts, so a blueprint can be pointed here."""
    assert NOTIFY_SEND_SCHEMA({"message": "hi"}) == {"message": "hi"}

    # A single target is written without a list far more often than with one.
    assert NOTIFY_SEND_SCHEMA({"message": "hi", "target": "5555550101"})["target"] == [
        "5555550101"
    ]

    assert NOTIFY_SEND_SCHEMA(
        {
            "message": "hi",
            "title": "Alert",
            "target": ["Sam", "Alice"],
            "data": {"image": "/config/www/photo.jpg"},
        }
    )["data"] == {"image": "/config/www/photo.jpg"}

    with pytest.raises(vol.Invalid):
        NOTIFY_SEND_SCHEMA({"title": "Alert"})


def _notifier(account: _Account, contact_id: str = "contact_sam") -> TextNowNotifyEntity:
    entity = TextNowNotifyEntity(account, contact_id, CONTACTS[contact_id])
    entity.hass = account.hass
    return entity


def test_a_contact_gets_a_notify_entity_that_texts_them(account: _Account) -> None:
    entity = _notifier(account)

    _run(entity.async_send_message("The door is open", "Alert"))

    assert account.sent == [(SAM, "Alert\nThe door is open")]


def test_the_notify_entity_accepts_a_title(account: _Account) -> None:
    """Without the feature flag Home Assistant hides the title field."""
    assert _notifier(account).supported_features is NotifyEntityFeature.TITLE


def test_the_notify_entity_is_named_after_the_contact(account: _Account) -> None:
    entity = _notifier(account, "contact_alice")

    assert entity.name == "Alice"
    assert entity.unique_id == "textnow_notify_contact_alice"


def test_the_notify_entity_stays_available_when_a_poll_fails(
    account: _Account,
) -> None:
    """A service call skips an unavailable entity, which would drop the text."""
    assert account.last_update_success is False
    assert _notifier(account).available is True


def test_the_notify_entity_belongs_to_the_account_device(account: _Account) -> None:
    entity = _notifier(account)

    assert entity.device_info["identifiers"] == {(DOMAIN, account.entry.entry_id)}
