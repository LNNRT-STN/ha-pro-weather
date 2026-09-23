"""Shared fixtures: a fake API response and a set-up config entry."""

from datetime import UTC, datetime, timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proweather_solar.const import DOMAIN

TOKEN = "pws_" + "ab" * 32
URL = "https://pro-weather.com/api/solar"
# Wednesday 2026-09-24 00:00 UTC: the first slot of every fake response.
T0 = datetime(2026, 9, 24, tzinfo=UTC)


def iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def make_body(watts=lambda i: 1000, hours: int = 48, start: datetime = T0) -> dict:
    """An /api/solar 200 body with `hours` hourly slots from `start`."""
    slots = []
    for i in range(hours):
        s = start + timedelta(hours=i)
        w = watts(i)
        slots.append(
            {"start": iso(s), "end": iso(s + timedelta(hours=1)), "value": w, "wh": w, "ghi": 0}
        )
    return {
        "generatedAt": iso(start),
        "issuedAt": iso(start),
        "corrected": True,
        "station": {"name": "Ardooie", "timezone": "Europe/Brussels"},
        "arrays": [{"name": "Roof south", "kwp": 5.2}],
        "slots": slots,
        "wh_hours": {x["start"]: x["wh"] for x in slots},
        "daily": {},
    }


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Ardooie solar",
        data={"token": TOKEN, "base_url": "https://pro-weather.com"},
        unique_id="u",
    )


@pytest.fixture
async def setup(hass, entry, aioclient_mock, freezer):
    """Entry set up at 2026-09-24 06:30 UTC, HA in America/New_York."""
    await hass.config.async_set_time_zone("America/New_York")
    freezer.move_to("2026-09-24T06:30:00Z")
    aioclient_mock.get(URL, json=make_body())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
