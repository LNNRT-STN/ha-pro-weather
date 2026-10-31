"""Sensors, weather entity and warnings of a station entry (2026-10-31 15:30 UTC)."""

from datetime import UTC, datetime

import pytest
from homeassistant.components.sensor import DEVICE_CLASS_UNITS, SensorDeviceClass
from homeassistant.components.weather import DOMAIN as WEATHER_DOMAIN
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.proweather_solar.binary_sensor import active_warnings
from custom_components.proweather_solar.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.proweather_solar.energy import async_get_solar_forecast
from custom_components.proweather_solar.weather import condition, daily_forecast

from .conftest import VIEW, VIEW_URL, make_view

NOW = datetime(2026, 10, 31, 15, 30, tzinfo=UTC)
MS = int(NOW.timestamp() * 1000)


@pytest.mark.parametrize(
    ("device_class", "units"),
    [
        (SensorDeviceClass.TEMPERATURE, {"°C", "°F"}),
        (SensorDeviceClass.WIND_SPEED, {"km/h", "mph"}),
        (SensorDeviceClass.ATMOSPHERIC_PRESSURE, {"hPa", "inHg"}),
        (SensorDeviceClass.PRECIPITATION, {"mm", "in"}),
        (SensorDeviceClass.PRECIPITATION_INTENSITY, {"mm/h", "in/h"}),
        (SensorDeviceClass.DISTANCE, {"m", "ft", "km", "mi"}),
        (SensorDeviceClass.IRRADIANCE, {"W/m²"}),
        (SensorDeviceClass.HUMIDITY, {"%"}),
    ],
)
def test_site_units_are_ha_units(device_class, units):
    """Every unit string a Pro Weather site sends (lib/units.ts, all three
    presets) is HA's own spelling, which is why sensor.py passes them through."""
    assert units <= DEVICE_CLASS_UNITS[device_class]


async def test_sensors(hass, station, caplog):
    state = hass.states.get("sensor.weerstation_ardooie_temperature")
    assert float(state.state) == pytest.approx(11.6, abs=0.05)
    assert state.attributes["unit_of_measurement"] == "°C"
    # The long tail exists but is off until the user enables it.
    assert er.async_get(hass).async_get("sensor.weerstation_ardooie_rain_this_month").disabled
    assert hass.states.get("sensor.weerstation_ardooie_wind_direction").state == "82"
    aqi = hass.states.get("sensor.weerstation_ardooie_air_quality_index")
    assert aqi.state == "5"
    assert aqi.attributes["standard"] == "EAQI"
    high = hass.states.get("sensor.weerstation_ardooie_high_today")
    assert high.state == "11.9"
    assert high.attributes["at"] is not None
    assert "not a valid unit" not in caplog.text
    reg = er.async_get(hass)
    precision = {
        e: reg.async_get(f"sensor.weerstation_ardooie_{e}").options["sensor"][
            "suggested_display_precision"
        ]
        for e in ("temperature", "humidity", "atmospheric_pressure")
    }
    assert precision == {"temperature": 1, "humidity": 0, "atmospheric_pressure": 1}


async def test_converted_to_the_users_units(hass, station_entry, view, aioclient_mock, freezer):
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(NOW)
    aioclient_mock.get(VIEW_URL, json=view)
    station_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(station_entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.weerstation_ardooie_temperature")
    assert state.attributes["unit_of_measurement"] == "°F"
    assert float(state.state) == pytest.approx(52.9, abs=0.1)


@pytest.mark.parametrize("view", [make_view(current={**VIEW["current"], "uv": None})])
async def test_unmeasured_sensor_not_created(hass, station):
    assert hass.states.get("sensor.weerstation_ardooie_uv_index") is None
    assert hass.states.get("sensor.weerstation_ardooie_temperature") is not None


async def test_weather_entity(hass, station):
    state = hass.states.get("weather.weerstation_ardooie")
    # 15:00 UTC hour, WMO 3.
    assert state.state == "cloudy"
    assert state.attributes["temperature"] == pytest.approx(11.6, abs=0.05)
    assert "Local Forecast Engine" in state.attributes["attribution"]

    result = await hass.services.async_call(
        WEATHER_DOMAIN,
        "get_forecasts",
        {"entity_id": "weather.weerstation_ardooie", "type": "hourly"},
        blocking=True,
        return_response=True,
    )
    hourly = result["weather.weerstation_ardooie"]["forecast"]
    assert hourly[0]["datetime"] == "2026-10-31T15:00:00+00:00"
    assert hourly[0]["condition"] == "cloudy"

    result = await hass.services.async_call(
        WEATHER_DOMAIN,
        "get_forecasts",
        {"entity_id": "weather.weerstation_ardooie", "type": "daily"},
        blocking=True,
        return_response=True,
    )
    daily = result["weather.weerstation_ardooie"]["forecast"]
    assert daily[0]["temperature"] == 11.1
    assert daily[0]["templow"] == 4.6
    assert daily[0]["condition"] == "fog"


def test_condition_at_night():
    assert condition(0, is_day=False) == "clear-night"
    assert condition(2, is_day=False) == "partlycloudy"
    assert condition(1234) is None


def test_daily_drops_a_day_that_ended():
    view = make_view()
    assert len(daily_forecast(view, NOW)) == len(view["forecast"]["daily"])
    day1 = view["forecast"]["daily"][1]["ts"]
    # The last second of day 1, then the first of day 2 (a cached view).
    last_second = datetime.fromtimestamp(day1 + 86400 - 1, UTC)
    assert daily_forecast(view, last_second)[0]["datetime"] == _iso(day1)
    next_day = datetime.fromtimestamp(day1 + 86400, UTC)
    assert daily_forecast(view, next_day)[0]["datetime"] == _iso(day1 + 86400)


def _iso(ts):
    return datetime.fromtimestamp(ts, UTC).isoformat()


def _warning(level, onset, expires):
    return {
        "id": level,
        "level": level,
        "category": "wind",
        "event": "Wind",
        "onsetMs": onset,
        "expiresMs": expires,
        "headline": None,
        "url": None,
    }


def test_active_warnings():
    hour = 3_600_000
    view = {
        "warnings": [
            _warning("yellow", MS - hour, MS + hour),
            _warning("red", None, None),
            _warning("orange", MS + hour, MS + 2 * hour),  # not yet
            _warning("red", MS - 2 * hour, MS - hour),  # over
        ]
    }
    assert [w["level"] for w in active_warnings(view, NOW)] == ["red", "yellow"]


@pytest.mark.parametrize(
    "view", [make_view(warnings=[_warning("orange", MS - 1000, MS + 3_600_000)])]
)
async def test_warning_sensor(hass, station):
    state = hass.states.get("binary_sensor.weerstation_ardooie_weather_warning")
    assert state.state == "on"
    assert state.attributes["highest_level"] == "orange"
    assert state.attributes["warnings"][0]["event"] == "Wind"


async def test_no_warning(hass, station):
    state = hass.states.get("binary_sensor.weerstation_ardooie_weather_warning")
    assert state.state == "off"


async def test_no_solar_forecast_and_diagnostics(hass, station):
    assert await async_get_solar_forecast(hass, station.entry_id) is None
    diag = await async_get_config_entry_diagnostics(hass, station)
    assert diag["response"]["station"]["subdomain"] == "ardooie"
