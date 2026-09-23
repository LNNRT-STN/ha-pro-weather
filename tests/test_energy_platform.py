"""Core's energy integration picks up energy.py (needs the recorder)."""

import pytest
from homeassistant.setup import async_setup_component

from .conftest import URL, make_body


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    # Overrides the conftest fixture so the recorder starts before `hass`,
    # which recorder_mock requires.
    return


async def test_energy_integration_discovers_the_platform(
    hass, hass_ws_client, entry, aioclient_mock
):
    # End to end through core's energy integration: it lists this domain as a
    # solar forecast provider only if energy.py matches its platform contract.
    aioclient_mock.get(URL, json=make_body())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert await async_setup_component(hass, "energy", {})
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "energy/info"})
    msg = await client.receive_json()
    assert msg["success"]
    assert "proweather_solar" in msg["result"]["solar_forecast_domains"]
