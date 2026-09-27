"""Notify platform for TextNow.

Home Assistant reaches notifications two ways. The notify.textnow service
takes a message and a target, which is what automations and blueprints written
for other SMS integrations already send. The entities created here are the
other way: one per contact, so the notify entity picker, notify.send_message
and anything built around them have something to point at.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import services
from .const import DOMAIN
from .coordinator import TextNowDataUpdateCoordinator
from .sensor import TextNowEntity
from .storage import TextNowStorage

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a notify entity for every contact of this account."""
    coordinator: TextNowDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    storage_helper = TextNowStorage(hass, entry.entry_id)

    notifiers: dict[str, TextNowNotifyEntity] = {}

    contacts = await storage_helper.async_get_contacts()
    for contact_id, contact_data in contacts.items():
        notifiers[contact_id] = TextNowNotifyEntity(
            coordinator, contact_id, contact_data
        )

    async_add_entities(list(notifiers.values()))

    async def contact_added_listener(event) -> None:
        """Add a notify entity for a contact created from the panel or options."""
        contact_id = event.data.get("contact_id")
        name = event.data.get("name")
        phone = event.data.get("phone")
        if not contact_id or not name or not phone:
            return
        if contact_id in notifiers:
            return
        notifier = TextNowNotifyEntity(
            coordinator, contact_id, {"name": name, "phone": phone}
        )
        notifiers[contact_id] = notifier
        async_add_entities([notifier])

    async def contact_deleted_listener(event) -> None:
        """Remove the notify entity of a deleted contact."""
        notifier = notifiers.pop(event.data.get("contact_id"), None)
        if notifier is not None:
            await notifier.async_remove(force_remove=True)

    entry.async_on_unload(
        hass.bus.async_listen(f"{DOMAIN}_contact_added", contact_added_listener)
    )
    entry.async_on_unload(
        hass.bus.async_listen(f"{DOMAIN}_contact_deleted", contact_deleted_listener)
    )


class TextNowNotifyEntity(TextNowEntity, NotifyEntity):
    """Texts one contact when notify.send_message targets it."""

    _attr_icon = "mdi:message-arrow-right"
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(
        self,
        coordinator: TextNowDataUpdateCoordinator,
        contact_id: str,
        contact_data: dict[str, Any],
    ) -> None:
        """Initialize the notify entity."""
        super().__init__(coordinator)
        self._contact_id = contact_id
        self._attr_name = contact_data.get("name", contact_id)
        self._attr_unique_id = f"textnow_notify_{contact_id}"
        self._phone = contact_data.get("phone", "")

    @property
    def available(self) -> bool:
        """Stay available, the way the status sensor does.

        A service call skips an unavailable entity without saying so, so a
        notifier that went unavailable whenever a poll failed would drop
        notifications silently. A send that cannot go through raises instead,
        which is something the user can see and act on.
        """
        return True

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send the notification to this contact as a text message."""
        await services.async_send_message(
            self.hass,
            self.coordinator,
            {
                "phone": self._phone,
                "message": services.notify_text(message, title),
            },
        )
