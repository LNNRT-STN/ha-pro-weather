"""The station as a weather entity: its own readings now, and the forecast
its site shows (the Local Forecast Engine's temperatures where it has run)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.components.weather import (
    ATTR_CONDITION_CLEAR_NIGHT,
    ATTR_CONDITION_CLOUDY,
    ATTR_CONDITION_FOG,
    ATTR_CONDITION_LIGHTNING,
    ATTR_CONDITION_PARTLYCLOUDY,
    ATTR_CONDITION_POURING,
    ATTR_CONDITION_RAINY,
    ATTR_CONDITION_SNOWY,
    ATTR_CONDITION_SUNNY,
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .entity import StationEntity
from .station import StationConfigEntry

# WMO weather codes, as Open-Meteo sends them, to HA conditions. The same
# table as HA's own open_meteo integration (components/open_meteo/const.py,
# 2026.9). Copied rather than imported: importing another integration makes
# it a dependency.
WMO_CONDITION = {
    0: ATTR_CONDITION_SUNNY,
    1: ATTR_CONDITION_SUNNY,
    2: ATTR_CONDITION_PARTLYCLOUDY,
    3: ATTR_CONDITION_CLOUDY,
    45: ATTR_CONDITION_FOG,
    48: ATTR_CONDITION_FOG,
    51: ATTR_CONDITION_RAINY,
    53: ATTR_CONDITION_RAINY,
    55: ATTR_CONDITION_RAINY,
    56: ATTR_CONDITION_RAINY,
    57: ATTR_CONDITION_RAINY,
    61: ATTR_CONDITION_RAINY,
    63: ATTR_CONDITION_RAINY,
    65: ATTR_CONDITION_POURING,
    66: ATTR_CONDITION_RAINY,
    67: ATTR_CONDITION_POURING,
    71: ATTR_CONDITION_SNOWY,
    73: ATTR_CONDITION_SNOWY,
    75: ATTR_CONDITION_SNOWY,
    77: ATTR_CONDITION_SNOWY,
    80: ATTR_CONDITION_RAINY,
    81: ATTR_CONDITION_RAINY,
    82: ATTR_CONDITION_POURING,
    85: ATTR_CONDITION_SNOWY,
    86: ATTR_CONDITION_SNOWY,
    95: ATTR_CONDITION_LIGHTNING,
    96: ATTR_CONDITION_LIGHTNING,
    99: ATTR_CONDITION_LIGHTNING,
}


def condition(code: Any, is_day: bool = True) -> str | None:
    found = WMO_CONDITION.get(code)
    if found == ATTR_CONDITION_SUNNY and not is_day:
        return ATTR_CONDITION_CLEAR_NIGHT
    return found


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat()


def hourly_forecast(view: dict[str, Any], now: datetime) -> list[Forecast]:
    """From the hour `now` is in onwards. The view is cached and its list
    starts an hour before it was built, so it is cut against HA's clock
    rather than trusted to start at now."""
    start = now.replace(minute=0, second=0, microsecond=0).timestamp()
    return [
        Forecast(
            datetime=_iso(h["ts"]),
            condition=condition(h.get("code"), h.get("isDay", True)),
            native_temperature=h.get("temp"),
            native_apparent_temperature=h.get("feelsLike"),
            precipitation_probability=h.get("precipProb"),
            native_precipitation=h.get("precipAmount"),
            native_wind_speed=h.get("windSpeed"),
            native_wind_gust_speed=h.get("windGust"),
            wind_bearing=h.get("windDir"),
            humidity=h.get("humidity"),
            native_pressure=h.get("pressure"),
            uv_index=h.get("uv"),
            is_daytime=h.get("isDay"),
        )
        for h in (view.get("forecast") or {}).get("hourly") or []
        if h["ts"] >= start
    ]


def daily_forecast(view: dict[str, Any], now: datetime) -> list[Forecast]:
    """Each day's `ts` is its local midnight; a day that already ended (a view
    cached across midnight) is dropped."""
    cutoff = now.timestamp() - 86400
    return [
        Forecast(
            datetime=_iso(d["ts"]),
            condition=condition(d.get("code")),
            native_temperature=d.get("tMax"),
            native_templow=d.get("tMin"),
            precipitation_probability=d.get("precipProb"),
            native_precipitation=d.get("precipSum"),
            native_wind_speed=d.get("windMax"),
            uv_index=d.get("uvMax"),
        )
        for d in (view.get("forecast") or {}).get("daily") or []
        if d["ts"] > cutoff
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StationConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([StationWeather(entry.runtime_data, "weather")])


def _value(block: Any) -> float | None:
    return block.get("value") if isinstance(block, dict) else None


class StationWeather(StationEntity, WeatherEntity):
    _attr_name = None  # the device's name: "Weerstation Ardooie"
    _attr_supported_features = WeatherEntityFeature.FORECAST_DAILY | (
        WeatherEntityFeature.FORECAST_HOURLY
    )

    @property
    def _current(self) -> dict[str, Any]:
        return self.coordinator.data.get("current") or {}

    @property
    def _forecast(self) -> dict[str, Any]:
        return self.coordinator.data.get("forecast") or {}

    @property
    def condition(self) -> str | None:
        # The station measures no sky, so "now" is the forecast hour now is in.
        now = dt_util.utcnow().timestamp()
        hours = [h for h in self._forecast.get("hourly") or [] if h["ts"] <= now]
        return condition(hours[-1].get("code"), hours[-1].get("isDay", True)) if hours else None

    @property
    def native_temperature(self) -> float | None:
        return _value(self._current.get("temperature"))

    @property
    def native_apparent_temperature(self) -> float | None:
        return _value(self._current.get("feelsLike"))

    @property
    def native_dew_point(self) -> float | None:
        return _value(self._current.get("dewPoint"))

    @property
    def humidity(self) -> float | None:
        return _value(self._current.get("humidity"))

    @property
    def native_pressure(self) -> float | None:
        return _value(self._current.get("pressure"))

    @property
    def native_wind_speed(self) -> float | None:
        return _value(self._current.get("wind"))

    @property
    def native_wind_gust_speed(self) -> float | None:
        return _value(self._current.get("windGust"))

    @property
    def wind_bearing(self) -> float | None:
        return self._current.get("windDirDeg")

    @property
    def uv_index(self) -> float | None:
        return _value(self._current.get("uv"))

    # The site's unit strings are HA's own (°C, km/h, hPa, mm and their
    # imperial twins; tests/test_station_sensor.py pins that), so they pass
    # straight through and HA converts to the user's units.
    @property
    def native_temperature_unit(self) -> str | None:
        return self._forecast.get("tempUnit")

    @property
    def native_pressure_unit(self) -> str | None:
        return self._forecast.get("pressureUnit")

    @property
    def native_wind_speed_unit(self) -> str | None:
        return self._forecast.get("windUnit")

    @property
    def native_precipitation_unit(self) -> str | None:
        return self._forecast.get("rainUnit")

    @property
    def attribution(self) -> str:
        if self._forecast.get("temperatureSource") == "proweather":
            return "Station readings and Local Forecast Engine by Pro Weather"
        return "Station readings by Pro Weather, forecast by Open-Meteo"

    async def async_forecast_daily(self) -> list[Forecast] | None:
        return daily_forecast(self.coordinator.data, dt_util.utcnow())

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        return hourly_forecast(self.coordinator.data, dt_util.utcnow())

    @callback
    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()
        # Cards subscribed to the forecast only hear about a new one this way.
        self.hass.async_create_task(self.async_update_listeners(None))
