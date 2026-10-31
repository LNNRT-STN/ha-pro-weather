"""The blueprints, run as real automations against a station entry."""

import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

from .conftest import VIEW, make_view

BLUEPRINTS = Path(__file__).parent.parent / "blueprints" / "automation" / "proweather"
WEATHER = "weather.weerstation_ardooie"
FIRED = [{"event": "pw_test"}]


async def _automation(hass, blueprint, inputs, events):
    dest = Path(hass.config.path("blueprints/automation/proweather"))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINTS / blueprint, dest / blueprint)
    hass.bus.async_listen("pw_test", lambda e: events.append(e))
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": blueprint,
                "use_blueprint": {
                    "path": f"proweather/{blueprint}",
                    "input": {**inputs, "actions": FIRED},
                },
            }
        },
    )
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    # The automations' time triggers stay scheduled past the test.
    return True


@pytest.fixture(autouse=True)
def _cleanup(hass):
    yield
    shutil.rmtree(hass.config.path("blueprints"), ignore_errors=True)


@pytest.mark.parametrize("limit, fires", [(4, True), (3.5, False)])
async def test_freeze_forecast(hass, station, freezer, limit, fires):
    """Tomorrow's low in the fixture is 4.0 °C; checked at 15:45 UTC."""
    events = []
    at = (dt_util.now() + timedelta(minutes=15)).strftime("%H:%M:00")
    await _automation(
        hass,
        "freeze_alert.yaml",
        {
            "weather": WEATHER,
            "temperature": "sensor.weerstation_ardooie_temperature",
            "limit": limit,
            "check_time": at,
        },
        events,
    )
    freezer.tick(timedelta(minutes=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert bool(events) is fires


async def test_rain_measured(hass, station):
    events = []
    rate = "sensor.weerstation_ardooie_rain_rate"
    await _automation(
        hass, "rain_start.yaml", {"rain_rate": rate, "weather": WEATHER, "quiet_hours": 0}, events
    )
    hass.states.async_set(rate, "0.4", {"unit_of_measurement": "mm/h"})
    await hass.async_block_till_done()
    assert len(events) == 1


def _wet_view():
    hourly = [{**h, "precipProb": 90} for h in VIEW["forecast"]["hourly"]]
    return make_view(forecast={**VIEW["forecast"], "hourly": hourly})


@pytest.mark.parametrize("view, fires", [(_wet_view(), True), (make_view(), False)])
async def test_rain_forecast(hass, station, freezer, fires):
    events = []
    await _automation(
        hass,
        "rain_start.yaml",
        {
            "rain_rate": "sensor.weerstation_ardooie_rain_rate",
            "weather": WEATHER,
            # No quiet period: its delay would hold the run past the test.
            "quiet_hours": 0,
        },
        events,
    )
    freezer.move_to("2026-10-31T15:45:00Z")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert bool(events) is fires


async def test_high_wind_closes_covers(hass, station):
    events = []
    closed = async_mock_service(hass, "cover", "close_cover")
    gust = "sensor.weerstation_ardooie_wind_gust"
    await _automation(
        hass,
        "high_wind.yaml",
        {"gust": gust, "limit": 40, "covers": {"entity_id": "cover.awning"}},
        events,
    )
    hass.states.async_set(gust, "55", {"unit_of_measurement": "km/h"})
    await hass.async_block_till_done()
    assert closed[0].data["entity_id"] == ["cover.awning"]
    assert len(events) == 1
