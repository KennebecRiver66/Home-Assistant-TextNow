"""Sensor platform for TextNow."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DEVICE_NAME,
    DOMAIN,
    ATTR_PHONE,
    ATTR_LAST_INBOUND,
    ATTR_LAST_INBOUND_TS,
    ATTR_LAST_OUTBOUND,
    ATTR_LAST_OUTBOUND_TS,
    ATTR_PENDING,
    ATTR_CONTEXT,
    ATTR_TEXT,
    ATTR_TIMESTAMP,
    EVENT_MESSAGE_RECEIVED,
    EVENT_REPLY_PARSED,
)
from .coordinator import TextNowDataUpdateCoordinator
from .storage import TextNowStorage

_LOGGER = logging.getLogger(__name__)

# Home Assistant rejects states longer than this
MAX_STATE_LENGTH = 255

STATUS_CONNECTED = "connected"
STATUS_REAUTH_REQUIRED = "reauth_required"
STATUS_DISCONNECTED = "disconnected"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TextNow sensors from a config entry."""
    coordinator: TextNowDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    storage_helper = TextNowStorage(hass, entry.entry_id)

    contact_sensors: dict[str, TextNowContactSensor] = {}

    contacts = await storage_helper.async_get_contacts()
    for contact_id, contact_data in contacts.items():
        contact_sensors[contact_id] = TextNowContactSensor(
            coordinator, storage_helper, contact_id, contact_data
        )

    async_add_entities([TextNowStatusSensor(coordinator), *contact_sensors.values()])

    async def contact_added_listener(event) -> None:
        """Add a sensor for a contact created from the panel or options."""
        contact_id = event.data.get("contact_id")
        name = event.data.get("name")
        phone = event.data.get("phone")
        if not contact_id or not name or not phone:
            return
        if contact_id in contact_sensors:
            return
        sensor = TextNowContactSensor(
            coordinator, storage_helper, contact_id, {"name": name, "phone": phone}
        )
        contact_sensors[contact_id] = sensor
        async_add_entities([sensor])

    async def contact_deleted_listener(event) -> None:
        """Remove the sensor of a deleted contact."""
        sensor = contact_sensors.pop(event.data.get("contact_id"), None)
        if sensor is not None:
            await sensor.async_remove(force_remove=True)

    entry.async_on_unload(
        hass.bus.async_listen(f"{DOMAIN}_contact_added", contact_added_listener)
    )
    entry.async_on_unload(
        hass.bus.async_listen(f"{DOMAIN}_contact_deleted", contact_deleted_listener)
    )


class TextNowEntity(CoordinatorEntity[TextNowDataUpdateCoordinator]):
    """Base entity attached to the TextNow device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TextNowDataUpdateCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._entry_id = coordinator.entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info, shared by every entity of this account."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=DEVICE_NAME,
            manufacturer="TextNow",
            model="SMS Integration",
            serial_number=self.coordinator.username or None,
        )


class TextNowStatusSensor(TextNowEntity, SensorEntity):
    """Reports whether the TextNow session still works."""

    _attr_translation_key = "status"
    _attr_icon = "mdi:cloud-check-variant"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATUS_CONNECTED, STATUS_DISCONNECTED, STATUS_REAUTH_REQUIRED]

    def __init__(self, coordinator: TextNowDataUpdateCoordinator) -> None:
        """Initialize the status sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"textnow_{self._entry_id}_status"

    @property
    def available(self) -> bool:
        """Stay available: the point of this sensor is to report trouble."""
        return True

    @property
    def native_value(self) -> str:
        """Return the connection state."""
        if self.coordinator.auth_failed:
            return STATUS_REAUTH_REQUIRED
        if self.coordinator.last_update_success:
            return STATUS_CONNECTED
        return STATUS_DISCONNECTED

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details that help diagnose a broken connection."""
        last_error = self.coordinator.last_exception
        return {
            "account": self.coordinator.username,
            "last_successful_poll": self.coordinator.last_success,
            "polling_interval_seconds": (
                int(self.coordinator.update_interval.total_seconds())
                if self.coordinator.update_interval
                else None
            ),
            "last_error": str(last_error) if last_error else None,
            # Named apart from the contact sensors' last_outbound, which is the
            # status of one message rather than a time for the whole account.
            "last_message_sent": self.coordinator.last_outbound,
            "keepalive_phone": self.coordinator.keepalive_phone or None,
            "keepalive_due": self.coordinator.keepalive_due_at,
        }


class TextNowContactSensor(TextNowEntity, SensorEntity):
    """Representation of a TextNow contact sensor."""

    def __init__(
        self,
        coordinator: TextNowDataUpdateCoordinator,
        storage: TextNowStorage,
        contact_id: str,
        contact_data: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._storage = storage
        self._contact_id = contact_id
        self._attr_name = contact_data.get("name", contact_id)
        self._attr_unique_id = f"textnow_{contact_id}"
        self._attr_icon = "mdi:message-text"
        self._phone = contact_data.get("phone", "")
        self._last_inbound: str | None = None
        self._last_inbound_ts: str | None = None
        self._last_outbound: str | None = None
        self._last_outbound_ts: str | None = None
        self._pending: dict[str, Any] = {}
        self._context: dict[str, Any] = {}

        self._unsub_message = None
        self._unsub_reply = None
        self._unsub_sent = None

    @property
    def native_value(self) -> str | None:
        """Return the last received message.

        None (unknown) means nothing has arrived yet; a dead session shows up
        as unavailable instead, so the two cases can be told apart.
        """
        if self._last_inbound is None:
            return None
        return self._last_inbound[:MAX_STATE_LENGTH]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {
            ATTR_PHONE: self._phone,
            ATTR_LAST_INBOUND: self._last_inbound,
            ATTR_LAST_INBOUND_TS: self._last_inbound_ts,
            ATTR_LAST_OUTBOUND: self._last_outbound,
            ATTR_LAST_OUTBOUND_TS: self._last_outbound_ts,
            ATTR_PENDING: self._pending,
            ATTR_CONTEXT: self._context,
        }

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()

        await self._update_state()

        self._unsub_message = self.hass.bus.async_listen(
            EVENT_MESSAGE_RECEIVED, self._handle_message_received
        )
        self._unsub_reply = self.hass.bus.async_listen(
            EVENT_REPLY_PARSED, self._handle_reply_parsed
        )
        self._unsub_sent = self.hass.bus.async_listen(
            f"{DOMAIN}_message_sent", self._handle_message_sent
        )

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        if self._unsub_message:
            self._unsub_message()
        if self._unsub_reply:
            self._unsub_reply()
        if self._unsub_sent:
            self._unsub_sent()
        await super().async_will_remove_from_hass()

    async def _handle_message_received(self, event) -> None:
        """Handle message received event."""
        if event.data.get(ATTR_PHONE) == self._phone:
            self._last_inbound = event.data.get(ATTR_TEXT, "")
            self._last_inbound_ts = event.data.get(ATTR_TIMESTAMP, "")
            await self._update_state()
            self.async_write_ha_state()

    async def _handle_reply_parsed(self, event) -> None:
        """Handle reply parsed event."""
        if event.data.get(ATTR_PHONE) == self._phone:
            await self._update_state()
            self.async_write_ha_state()

    @callback
    def _handle_message_sent(self, event) -> None:
        """Handle message sent event."""
        if event.data.get("phone") == self._phone:
            self._last_outbound = "Sent"
            self._last_outbound_ts = event.data.get(
                "timestamp", dt_util.utcnow().isoformat()
            )
            self.async_write_ha_state()

    async def _update_state(self) -> None:
        """Update sensor state from storage."""
        self._pending = await self._storage.async_get_pending(self._phone)
        self._context = await self._storage.async_get_context(self._phone)
