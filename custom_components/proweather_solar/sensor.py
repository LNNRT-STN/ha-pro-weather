"""Forecast sensors. "Today" and "tomorrow" are Home Assistant's own time
zone, not the station's: a household plans its day by its own clock, and the
API's `daily` (station-local) is deliberately not used here."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ProWeatherConfigEntry, SolarData
from .entity import ProWeatherEntity

HALF_HOUR = timedelta(minutes=30)


def day_bounds(offset: int, now: datetime | None = None) -> tuple[datetime, datetime]:
    """[start, end) of today (offset 0) or tomorrow (1) in HA's time zone.
    Built from dates, not now + 24 h, so a 23 or 25 hour DST day is right."""
    today = dt_util.as_local(now or dt_util.now()).date()
    return (
        dt_util.start_of_local_day(today + timedelta(days=offset)),
        dt_util.start_of_local_day(today + timedelta(days=offset + 1)),
    )


def detailed_forecast(data: SolarData, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """The BJReplay Solcast integration's `detailedForecast` attribute:
    half-hourly periods, `pv_estimate` in kW (mean power, not energy), with
    `period_start` in local time with its offset.

    Half-hourly on purpose: Predbat divides the sum of these by the sensor's
    kWh state to tell kW-per-30-min data (factor 2) from kWh-per-slot data
    (factor 1), and its docs warn that hourly entries read as half-hours
    double the forecast. Each hourly slot therefore becomes two half-hours
    at the same mean power.
    """
    out = []
    for s in data.slots_between(start, end):
        kw = round(s.watts / 1000, 4)
        for half in (s.start, s.start + HALF_HOUR):
            out.append(
                {
                    "period_start": dt_util.as_local(half).isoformat(),
                    "pv_estimate": kw,
                    # Phase 3 brings real P10/P90 from the engine's model
                    # spread; until then both equal the estimate, which
                    # Predbat reads as "no uncertainty information".
                    "pv_estimate10": kw,
                    "pv_estimate90": kw,
                }
            )
    return out


def _peak(data: SolarData):
    return max(data.slots_between(*day_bounds(0)), key=lambda s: s.watts, default=None)


def _kwh(wh: float) -> float:
    return round(wh / 1000, 3)


@dataclass(frozen=True, kw_only=True)
class ProWeatherSensorDescription(SensorEntityDescription):
    value_fn: Callable[[SolarData], Any]
    # Offset of the day whose detailedForecast goes in the attributes.
    detail_day: int | None = None


def _this_hour(data: SolarData):
    return data.slot_at(dt_util.utcnow())


def _next_hour(data: SolarData):
    return data.slot_at(dt_util.utcnow() + timedelta(hours=1))


# Forecast energy gets no state_class, on purpose: TOTAL or TOTAL_INCREASING
# would make the recorder treat a forecast as a meter and compile long-term
# energy statistics out of it. HA's own Forecast.Solar integration does the
# same. Power now is a MEASUREMENT so its history graphs as a curve.
SENSORS: tuple[ProWeatherSensorDescription, ...] = (
    ProWeatherSensorDescription(
        key="power_now",
        translation_key="power_now",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: (s := _this_hour(d)) and round(s.watts),
    ),
    ProWeatherSensorDescription(
        key="energy_this_hour",
        translation_key="energy_this_hour",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        value_fn=lambda d: (s := _this_hour(d)) and round(s.wh),
    ),
    ProWeatherSensorDescription(
        key="energy_next_hour",
        translation_key="energy_next_hour",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        value_fn=lambda d: (s := _next_hour(d)) and round(s.wh),
    ),
    ProWeatherSensorDescription(
        key="energy_today",
        translation_key="energy_today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=lambda d: _kwh(d.wh_between(*day_bounds(0))),
        detail_day=0,
    ),
    ProWeatherSensorDescription(
        key="energy_remaining_today",
        translation_key="energy_remaining_today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=lambda d: _kwh(d.wh_remaining(dt_util.utcnow(), day_bounds(0)[1])),
    ),
    ProWeatherSensorDescription(
        key="energy_tomorrow",
        translation_key="energy_tomorrow",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=lambda d: _kwh(d.wh_between(*day_bounds(1))),
        detail_day=1,
    ),
    ProWeatherSensorDescription(
        key="peak_power_today",
        translation_key="peak_power_today",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: (p := _peak(d)) and round(p.watts),
    ),
    ProWeatherSensorDescription(
        key="peak_time_today",
        translation_key="peak_time_today",
        device_class=SensorDeviceClass.TIMESTAMP,
        # The start of the hour with the highest mean power.
        value_fn=lambda d: (p := _peak(d)) and p.watts > 0 and p.start or None,
    ),
    ProWeatherSensorDescription(
        key="issued_at",
        translation_key="issued_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.issued_at,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProWeatherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(ProWeatherSensor(entry.runtime_data, d) for d in SENSORS)


class ProWeatherSensor(ProWeatherEntity, SensorEntity):
    entity_description: ProWeatherSensorDescription
    # Up to 96 half-hour dicts: useful live (Predbat reads the state
    # machine), noise in the recorder database.
    _unrecorded_attributes = frozenset({"detailedForecast"})

    def __init__(self, coordinator, description: ProWeatherSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.detail_day is None:
            return None
        start, end = day_bounds(self.entity_description.detail_day)
        return {"detailedForecast": detailed_forecast(self.coordinator.data, start, end)}
