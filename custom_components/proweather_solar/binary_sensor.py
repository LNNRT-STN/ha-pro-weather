"""The "corrected" flag."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ProWeatherConfigEntry
from .entity import ProWeatherEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProWeatherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([CorrectedSensor(entry.runtime_data, "corrected")])


class CorrectedSensor(ProWeatherEntity, BinarySensorEntity):
    """On once the station's solar sensor has scored the weather models for
    long enough that the forecast uses this station's own model weights."""

    _attr_translation_key = "corrected"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.corrected
