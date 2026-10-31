"""The solar forecast's "corrected" flag, and a station's official warnings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ProWeatherConfigEntry
from .entity import ProWeatherEntity, StationEntity
from .station import StationConfigEntry, StationCoordinator

LEVELS = ("yellow", "orange", "red")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProWeatherConfigEntry | StationConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if isinstance(entry.runtime_data, StationCoordinator):
        async_add_entities([WarningSensor(entry.runtime_data, "warning")])
        return
    async_add_entities([CorrectedSensor(entry.runtime_data, "corrected")])


class CorrectedSensor(ProWeatherEntity, BinarySensorEntity):
    """On once the station's solar sensor has scored the weather models for
    long enough that the forecast uses this station's own model weights."""

    _attr_translation_key = "corrected"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.corrected


def active_warnings(view: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """The warnings in force at `now`, most severe first. The view is cached
    for minutes and warnings are issued ahead, so onset and expiry are checked
    here; a missing one counts as open-ended."""
    ms = now.timestamp() * 1000
    return sorted(
        (
            w
            for w in view.get("warnings") or []
            if (w.get("onsetMs") or 0) <= ms < (w.get("expiresMs") or float("inf"))
        ),
        key=lambda w: -LEVELS.index(w["level"]) if w.get("level") in LEVELS else 0,
    )


class WarningSensor(StationEntity, BinarySensorEntity):
    """On while an official MeteoAlarm or NWS warning covers the station."""

    _attr_translation_key = "warning"
    _attr_device_class = BinarySensorDeviceClass.SAFETY
    # The list can be long and its text is the issuer's; useful to an
    # automation reading it live, noise in the recorder.
    _unrecorded_attributes = frozenset({"warnings"})

    @property
    def _active(self) -> list[dict[str, Any]]:
        return active_warnings(self.coordinator.data, dt_util.utcnow())

    @property
    def is_on(self) -> bool:
        return bool(self._active)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        active = self._active
        return {
            "highest_level": active[0].get("level") if active else None,
            "warnings": [
                {
                    "level": w.get("level"),
                    "category": w.get("category"),
                    "event": w.get("event"),
                    "headline": w.get("headline"),
                    "onset": _iso_ms(w.get("onsetMs")),
                    "expires": _iso_ms(w.get("expiresMs")),
                    "url": w.get("url"),
                }
                for w in active
            ],
        }


def _iso_ms(ms: Any) -> str | None:
    return dt_util.utc_from_timestamp(ms / 1000).isoformat() if ms else None
