"""Base entity: one service device per config entry."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ProWeatherCoordinator


class ProWeatherEntity(CoordinatorEntity[ProWeatherCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ProWeatherCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Pro Weather",
            model="Solar power forecast",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://pro-weather.com/dashboard",
        )

    @property
    def available(self) -> bool:
        # A forecast from an hour ago beats "unavailable" for anything that
        # plans a battery around it, so a failed poll (429, 503, network)
        # keeps showing the last good data instead of going unavailable.
        # The coordinator's own log line records the failure.
        return self.coordinator.data is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # "Power now", "this hour" and "today" move on at the top of the
        # hour (and at local midnight, also a top of the hour in every
        # zone HA supports bar a few :30/:45 ones, which catch up on the next
        # poll), not only when a poll lands up to 30 minutes later.
        self.async_on_remove(
            async_track_utc_time_change(self.hass, self._on_hour, minute=0, second=0)
        )

    @callback
    def _on_hour(self, _now: datetime) -> None:
        if self.coordinator.data is not None:
            self.async_write_ha_state()
