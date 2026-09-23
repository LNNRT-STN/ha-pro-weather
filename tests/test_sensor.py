"""Today, remaining and tomorrow in HA's zone (America/New_York, UTC-4),
not UTC and not the station's Europe/Brussels.

Fake forecast: 1000 W every hour from 2026-09-24 00:00 UTC for 48 h.
Now: 06:30 UTC = 02:30 local. Local today = 04:00Z Sep 24 to 04:00Z Sep 25:
24 slots = 24 kWh. Tomorrow = 04:00Z Sep 25 onwards, the forecast ends
at 00:00Z Sep 26, so 20 slots = 20 kWh. Remaining = half of 06:00Z + 21
full slots (07Z to 03Z) = 21.5 kWh. In UTC it would read 24 / 24 / 17.5.
"""

from datetime import timedelta

from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import URL, make_body

P = "sensor.ardooie_solar_"


def val(hass, key):
    return hass.states.get(P + key).state


async def test_local_day_maths(hass, setup):
    assert val(hass, "energy_today") == "24.0"
    assert val(hass, "energy_tomorrow") == "20.0"
    assert val(hass, "energy_remaining_today") == "21.5"
    assert val(hass, "power_now") == "1000"
    assert val(hass, "energy_this_hour") == "1000"
    assert val(hass, "energy_next_hour") == "1000"
    assert hass.states.get("binary_sensor.ardooie_solar_corrected_by_station").state == "on"
    assert val(hass, "forecast_issued") == "2026-09-24T00:00:00+00:00"


async def test_peak(hass, setup, aioclient_mock, freezer):
    # Peak at 16:00Z (noon local), plus a bigger one at 02:00Z, which is
    # still yesterday in New York and must not count.
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, json=make_body(lambda i: {2: 9000, 16: 4000}.get(i, 100)))
    await setup.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert val(hass, "peak_power_today") == "4000"
    assert val(hass, "peak_time_today") == "2026-09-24T16:00:00+00:00"


async def test_detailed_forecast_is_predbat_shape(hass, setup):
    detail = hass.states.get(P + "energy_today").attributes["detailedForecast"]
    # 24 local hours as 48 half-hours, local time with offset.
    assert len(detail) == 48
    assert detail[0] == {
        "period_start": "2026-09-24T00:00:00-04:00",
        "pv_estimate": 1.0,
        "pv_estimate10": 1.0,
        "pv_estimate90": 1.0,
    }
    assert detail[1]["period_start"] == "2026-09-24T00:30:00-04:00"
    # Predbat: sum(pv_estimate) / state must be 2.0 for kW-per-30-min data.
    assert sum(d["pv_estimate"] for d in detail) / float(val(hass, "energy_today")) == 2.0
    assert len(hass.states.get(P + "energy_tomorrow").attributes["detailedForecast"]) == 40


async def test_detailed_forecast_carries_the_band(hass, setup, aioclient_mock):
    body = make_body()
    for slot in body["slots"]:
        slot["p10"], slot["p90"] = 400, 1500
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, json=body)
    await setup.runtime_data.async_refresh()
    await hass.async_block_till_done()
    first = hass.states.get(P + "energy_today").attributes["detailedForecast"][0]
    assert (first["pv_estimate"], first["pv_estimate10"], first["pv_estimate90"]) == (1.0, 0.4, 1.5)


async def test_past_hours_survive_a_later_poll(hass, setup, aioclient_mock, freezer):
    # Six hours later the API serves from 12:00Z; 04Z-11Z are kept from the
    # first poll, so today is still the whole local day.
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, json=make_body(start=setup.runtime_data.data.slots[12].start, hours=36))
    freezer.tick(timedelta(hours=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 1
    assert val(hass, "energy_today") == "24.0"
    assert val(hass, "energy_remaining_today") == "15.5"


async def test_rolls_over_at_local_midnight(hass, setup, aioclient_mock, freezer):
    # 04:00Z Sep 25 is local midnight: tomorrow becomes today without a
    # poll landing (the API fails), thanks to the top-of-hour refresh.
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, status=503)
    freezer.move_to("2026-09-25T04:00:00Z")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert val(hass, "energy_today") == "20.0"
    assert val(hass, "energy_tomorrow") == "0.0"
