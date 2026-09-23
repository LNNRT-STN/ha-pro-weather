"""Measured production upload (POST /api/solar/production)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.proweather_solar.const import CONF_PRODUCTION_SENSOR, CONF_SCAN_INTERVAL
from custom_components.proweather_solar.production import (
    UPLOAD_HOURS,
    async_upload,
    async_upload_production,
    hours_from_statistics,
)

from .conftest import TOKEN, URL, make_body

POST_URL = "https://pro-weather.com/api/solar/production"
SENSOR = "sensor.inverter_energy"
STATS = "custom_components.proweather_solar.production._hourly_statistics"


def row(hour: int, change):
    start = datetime(2026, 9, 24, hour, tzinfo=UTC)
    return {
        "start": start.timestamp(),
        "end": (start + timedelta(hours=1)).timestamp(),
        "change": change,
    }


def test_hours_skip_missing_and_negative():
    rows = [row(9, 2140.04), row(10, None), row(11, -5.0), row(12, 0.0)]
    assert hours_from_statistics(rows) == [
        {"start": "2026-09-24T09:00:00Z", "wh": 2140.0},
        # A dark or idle hour is a real 0; only a missing one is left out.
        {"start": "2026-09-24T12:00:00Z", "wh": 0.0},
    ]


async def test_upload_posts_with_bearer_and_returns_answer(hass, aioclient_mock):
    answer = {"accepted": 1, "scale": {"active": False, "value": 1, "samples": 3}}
    aioclient_mock.post(POST_URL, json=answer)
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    hours = [{"start": "2026-09-24T09:00:00Z", "wh": 2140.0}]
    got = await async_upload(
        async_get_clientsession(hass), "https://pro-weather.com/", TOKEN, hours
    )
    assert got == answer
    method, url, body, headers = aioclient_mock.mock_calls[0][:4]
    assert (method, str(url)) == ("POST", POST_URL)
    assert body == {"hours": hours}
    assert headers["Authorization"] == f"Bearer {TOKEN}"


async def test_refused_upload_warns_without_the_token(hass, aioclient_mock, caplog):
    aioclient_mock.post(POST_URL, status=400, json={"error": "hours[0].wh must be 0 to 7800 Wh"})
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    got = await async_upload(async_get_clientsession(hass), "https://pro-weather.com", TOKEN, [])
    assert got is None
    assert "hours[0].wh must be" in caplog.text
    assert TOKEN not in caplog.text


async def test_network_error_never_raises(hass, aioclient_mock):
    aioclient_mock.post(POST_URL, exc=TimeoutError())
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    assert (
        await async_upload(async_get_clientsession(hass), "https://pro-weather.com", TOKEN, [])
        is None
    )


async def test_reads_the_trailing_day_in_wh(hass, aioclient_mock, freezer):
    freezer.move_to("2026-09-24T13:15:00Z")
    aioclient_mock.post(POST_URL, json={"accepted": 1})
    with patch(STATS, return_value=[row(12, 900.0)]) as stats:
        await async_upload_production(hass, "https://pro-weather.com", TOKEN, SENSOR)
    _, entity_id, start, end = stats.call_args.args
    assert entity_id == SENSOR
    # Finished hours only: up to 13:00, UPLOAD_HOURS back.
    assert end == datetime(2026, 9, 24, 13, tzinfo=UTC)
    assert end - start == timedelta(hours=UPLOAD_HOURS)
    assert aioclient_mock.mock_calls[0][2] == {
        "hours": [{"start": "2026-09-24T12:00:00Z", "wh": 900.0}]
    }


async def test_no_statistics_no_request(hass, aioclient_mock):
    with patch(STATS, return_value=[]):
        assert await async_upload_production(hass, "https://pro-weather.com", TOKEN, SENSOR) is None
    assert aioclient_mock.call_count == 0


async def test_options_flow_sets_and_clears_the_sensor(hass, setup):
    flow = await hass.config_entries.options.async_init(setup.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {CONF_SCAN_INTERVAL: 30, CONF_PRODUCTION_SENSOR: SENSOR}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup.options == {CONF_SCAN_INTERVAL: 30, CONF_PRODUCTION_SENSOR: SENSOR}
    await hass.async_block_till_done()
    flow = await hass.config_entries.options.async_init(setup.entry_id)
    await hass.config_entries.options.async_configure(flow["flow_id"], {CONF_SCAN_INTERVAL: 30})
    await hass.async_block_till_done()
    assert setup.options == {CONF_SCAN_INTERVAL: 30}


async def test_uploads_hourly_only_with_a_sensor(hass, entry, aioclient_mock, freezer):
    freezer.move_to("2026-09-24T06:30:00Z")
    aioclient_mock.get(URL, json=make_body())
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_PRODUCTION_SENSOR: SENSOR})
    with patch(
        "custom_components.proweather_solar.async_upload_production", return_value=None
    ) as upload:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert upload.call_count == 0
        freezer.move_to("2026-09-24T07:15:00Z")
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert upload.call_count == 1
        assert upload.call_args.args[1:] == ("https://pro-weather.com", TOKEN, SENSOR)
        # Unloading stops the timer.
        await hass.config_entries.async_unload(entry.entry_id)
        freezer.move_to("2026-09-24T08:15:00Z")
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert upload.call_count == 1
