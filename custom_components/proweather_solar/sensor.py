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
from homeassistant.const import DEGREE, EntityCategory, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ProWeatherConfigEntry, SolarData
from .entity import ProWeatherEntity, StationEntity
from .station import StationConfigEntry, StationCoordinator

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
                    # The engine's P10/P90 (the API's `p10`/`p90`), which
                    # Predbat's pessimistic weighting reads. Equal to the
                    # estimate where the API had no band.
                    "pv_estimate10": round(s.p10 / 1000, 4),
                    "pv_estimate90": round(s.p90 / 1000, 4),
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
    entry: ProWeatherConfigEntry | StationConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if isinstance(coordinator, StationCoordinator):
        # Only what this station measures: no permanently `unknown` UV or
        # air quality sensor on a station without the sensor.
        # ponytail: a sensor the station gains later appears on reload.
        async_add_entities(
            StationSensor(coordinator, d)
            for d in STATION_SENSORS
            if d.value_fn(coordinator.data) is not None
        )
        return
    async_add_entities(ProWeatherSensor(coordinator, d) for d in SENSORS)


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


# --- Weather station entries -------------------------------------------------
#
# Every value comes with the site's unit string, which is HA's own spelling
# (°C/°F, km/h/mph, hPa/inHg, mm/in, mm/h/in/h, m/ft, km/mi, W/m², %):
# tests/test_station_sensor.py pins that, so the unit passes straight through
# and HA converts it to the user's units. Read per update rather than once,
# because the owner can switch the site between metric and imperial.


def _block(*path: str) -> Callable[[dict], dict | None]:
    def read(view: dict) -> dict | None:
        node: Any = view
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        return node if isinstance(node, dict) else None

    return read


@dataclass(frozen=True, kw_only=True)
class StationSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], Any]
    unit_fn: Callable[[dict], str | None] = lambda _v: None
    attrs_fn: Callable[[dict], dict[str, Any]] | None = None


def _current(src: str, **kw: Any) -> StationSensorDescription:
    """A `{value, unit}` block of `current`."""
    read = _block("current", src)
    return StationSensorDescription(
        value_fn=lambda v: (read(v) or {}).get("value"),
        unit_fn=lambda v: (read(v) or {}).get("unit") or None,
        state_class=SensorStateClass.MEASUREMENT,
        **kw,
    )


def _today(src: str, field: str, **kw: Any) -> StationSensorDescription:
    """Today's high or low, from a `{hi, lo, unit, hiAtMs, loAtMs}` block."""
    read = _block("today", src)
    return StationSensorDescription(
        value_fn=lambda v: (read(v) or {}).get(field),
        unit_fn=lambda v: (read(v) or {}).get("unit") or None,
        attrs_fn=lambda v: {"at": _ms((read(v) or {}).get(f"{field}AtMs"))},
        state_class=SensorStateClass.MEASUREMENT,
        **kw,
    )


def _rain_total(src: str, **kw: Any) -> StationSensorDescription:
    read = _block("current", "rainTotals")
    return StationSensorDescription(
        value_fn=lambda v: (read(v) or {}).get(src),
        unit_fn=lambda v: (read(v) or {}).get("unit") or None,
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        **kw,
    )


def _ms(ms: Any) -> datetime | None:
    return dt_util.utc_from_timestamp(ms / 1000) if isinstance(ms, int | float) else None


_pressure_unit = _block("current", "pressure")
_skill = _block("forecast", "skill")
_aqi = _block("current", "aqi")

# Precipitation totals are MEASUREMENT, not TOTAL_INCREASING: the station's
# daily rain can be revised down a little, which TOTAL_INCREASING would read
# as a meter reset and add the whole day again to the long-term sum.
STATION_SENSORS: tuple[StationSensorDescription, ...] = (
    _current("temperature", key="temperature", device_class=SensorDeviceClass.TEMPERATURE),
    _current(
        "feelsLike",
        key="feels_like",
        translation_key="feels_like",
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    _current(
        "dewPoint",
        key="dew_point",
        translation_key="dew_point",
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    _current("humidity", key="humidity", device_class=SensorDeviceClass.HUMIDITY),
    _current("pressure", key="pressure", device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE),
    _current(
        "wind",
        key="wind_speed",
        translation_key="wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
    ),
    _current(
        "windGust",
        key="wind_gust",
        translation_key="wind_gust",
        device_class=SensorDeviceClass.WIND_SPEED,
    ),
    StationSensorDescription(
        key="wind_bearing",
        translation_key="wind_bearing",
        device_class=SensorDeviceClass.WIND_DIRECTION,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        value_fn=lambda v: (v.get("current") or {}).get("windDirDeg"),
        unit_fn=lambda _v: DEGREE,
        attrs_fn=lambda v: {"cardinal": (v.get("current") or {}).get("windCardinal")},
    ),
    _current(
        "rainToday",
        key="rain_today",
        translation_key="rain_today",
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    _current(
        "rainRate",
        key="rain_rate",
        translation_key="rain_rate",
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
    ),
    _current(
        "solar", key="solar", translation_key="solar", device_class=SensorDeviceClass.IRRADIANCE
    ),
    StationSensorDescription(
        key="uv",
        translation_key="uv",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: (_block("current", "uv")(v) or {}).get("value"),
    ),
    StationSensorDescription(
        key="aqi",
        device_class=SensorDeviceClass.AQI,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: (_aqi(v) or {}).get("value"),
        # The index is in the standard the owner picked (EAQI, US AQI...).
        attrs_fn=lambda v: {k: (_aqi(v) or {}).get(k) for k in ("standard", "category")},
    ),
    _today(
        "temperature",
        "hi",
        key="temperature_high_today",
        translation_key="temperature_high_today",
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    _today(
        "temperature",
        "lo",
        key="temperature_low_today",
        translation_key="temperature_low_today",
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    _today(
        "windGust",
        "hi",
        key="wind_gust_max_today",
        translation_key="wind_gust_max_today",
        device_class=SensorDeviceClass.WIND_SPEED,
        entity_registry_enabled_default=False,
    ),
    StationSensorDescription(
        key="pressure_trend",
        translation_key="pressure_trend",
        # A difference, but pressure units convert without an offset, so the
        # device class (and HA's conversion) is still right.
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda v: (v.get("current") or {}).get("pressureTrend3h"),
        unit_fn=lambda v: (_pressure_unit(v) or {}).get("unit") or None,
    ),
    _current(
        "cloudbase",
        key="cloud_base",
        translation_key="cloud_base",
        device_class=SensorDeviceClass.DISTANCE,
        entity_registry_enabled_default=False,
    ),
    _current(
        "windRun",
        key="wind_run",
        translation_key="wind_run",
        device_class=SensorDeviceClass.DISTANCE,
        entity_registry_enabled_default=False,
    ),
    _rain_total("last24h", key="rain_24h", translation_key="rain_24h"),
    _rain_total("month", key="rain_month", translation_key="rain_month"),
    _rain_total("year", key="rain_year", translation_key="rain_year"),
    _rain_total("storm", key="rain_storm", translation_key="rain_storm"),
    StationSensorDescription(
        key="beaufort",
        translation_key="beaufort",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda v: (_block("current", "windLive")(v) or {}).get("beaufort"),
    ),
    StationSensorDescription(
        key="observed_at",
        translation_key="observed_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda v: _ms(v.get("observedAtMs")),
    ),
    StationSensorDescription(
        key="forecast_error",
        translation_key="forecast_error",
        # A temperature DIFFERENCE: no device class, because HA would convert
        # it with the °C/°F offset. Shown in the site's own unit.
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda v: (_skill(v) or {}).get("maeStation"),
        unit_fn=lambda v: (_skill(v) or {}).get("unit") or None,
        attrs_fn=lambda v: {
            "models_error": (_skill(v) or {}).get("maeModels"),
            "days": (_skill(v) or {}).get("days"),
        },
    ),
)


class StationSensor(StationEntity, SensorEntity):
    entity_description: StationSensorDescription

    def __init__(self, coordinator, description: StationSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self.entity_description.unit_fn(self.coordinator.data)

    @property
    def suggested_display_precision(self) -> int | None:
        # The site sends full floats (1030.8509799 hPa). One decimal reads
        # right in metric units; inches need two. Whole units (%, W/m², m,
        # ft) and plain counts keep theirs.
        unit = self.native_unit_of_measurement
        if unit in ("in", "inHg", "in/h"):
            return 2
        if unit in ("%", "W/m²", "m", "ft", DEGREE) or unit is None:
            return 0
        return 1

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
