from datetime import timedelta

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.proweather_solar.const import DOMAIN

from .conftest import URL

POWER = "sensor.ardooie_solar_power_now"


@pytest.mark.parametrize("status", [429, 503])
async def test_failure_keeps_last_data(hass, setup, aioclient_mock, freezer, status):
    assert hass.states.get(POWER).state == "1000"
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, status=status, json={"error": "x"})
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    coordinator = setup.runtime_data
    assert aioclient_mock.call_count == 1
    assert not coordinator.last_update_success
    assert coordinator.data is not None
    assert hass.states.get(POWER).state == "1000"


async def test_401_starts_reauth(hass, setup, aioclient_mock, freezer):
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, status=401, json={"error": "Unknown token"})
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_setup_not_ready_on_503(hass, entry, aioclient_mock):
    aioclient_mock.get(URL, status=503)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
