from custom_components.proweather_solar.energy import async_get_solar_forecast

from .conftest import T0, iso


async def test_wh_hours(hass, setup):
    out = await async_get_solar_forecast(hass, setup.entry_id)
    assert list(out) == ["wh_hours"]
    hours = out["wh_hours"]
    assert len(hours) == 48
    # Keys parse back to the slot starts; values are Wh.
    assert hours[T0.isoformat()] == 1000
    assert iso(T0) == "2026-09-24T00:00:00Z"


async def test_unknown_entry(hass):
    assert await async_get_solar_forecast(hass, "nope") is None
