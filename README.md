# Pro Weather Solar Forecast for Home Assistant

An hour-by-hour power forecast for your own solar panels, from your
[Pro Weather](https://pro-weather.com) site, in Home Assistant: in the Energy
dashboard, as sensors for automations, and in the shape Predbat reads.

The forecast comes from weather models scored against your own station's
solar sensor. It needs a Pro Weather site on the Pro plan with panels set up
under **Setup > Solar forecast**.

## Install

With [HACS](https://hacs.xyz):

1. HACS > the three-dot menu > **Custom repositories**.
2. Repository `https://github.com/LNNRT-STN/ha-pro-weather`, type
   **Integration**, then **Add**.
3. Search for **Pro Weather Solar Forecast**, download it, and restart Home
   Assistant.

By hand: copy `custom_components/proweather_solar` into your Home Assistant
`config/custom_components/` folder and restart.

## Set up

1. In your Pro Weather dashboard, open **Setup > Solar forecast**, add your
   panel arrays if you have not yet, and copy the API token (it starts with
   `pws_`).
2. In Home Assistant: **Settings > Devices & services > Add integration >
   Pro Weather Solar Forecast**, and paste the token.

The token is checked with one request. The form tells you if the token is
unknown, the site is not on the Pro plan, or there are no panels to forecast
yet. If you regenerate the token later, Home Assistant asks for the new one.

**Options:** the update interval, 30 minutes by default and 15 at the least. A
new forecast arrives once an hour, so polling faster gains nothing.

## Energy dashboard

**Settings > Dashboards > Energy**, edit your solar production, and under
**Solar production forecast** tick the Pro Weather entry. The forecast line
appears over your measured production.

## Sensors

| Sensor | Unit | What it is |
| --- | --- | --- |
| Power now | W | Mean power forecast for the current hour |
| Energy this hour, Energy next hour | Wh | Energy for the current and next hour |
| Energy today | kWh | The whole of today, including hours already past |
| Energy remaining today | kWh | From now to midnight, the current hour pro rata |
| Energy tomorrow | kWh | All of tomorrow |
| Peak power today, Peak time today | W, time | The best hour today and when it starts |
| Corrected by station | on/off | See below (diagnostic) |
| Forecast issued | time | When the forecast behind these numbers was made (diagnostic) |

"Today" and "tomorrow" follow your Home Assistant time zone, not the
station's.

## Predbat

Energy today and Energy tomorrow carry a `detailedForecast` attribute in the
shape of the Solcast integration's: half-hourly periods with `period_start`,
`pv_estimate` (kW), `pv_estimate10` and `pv_estimate90`. Predbat reads it
without extra setup once `apps.yaml` points at these sensors, since the
default patterns only match Solcast's entity names:

```yaml
pv_forecast_today: sensor.ardooie_solar_energy_today
pv_forecast_tomorrow: sensor.ardooie_solar_energy_tomorrow
```

Use your own entity ids (the prefix is your station's name). Leave
`pv_forecast_d3` and `pv_forecast_d4` out: the forecast covers 48 hours.

`pv_estimate10` and `pv_estimate90` are the cautious and bright case: one
hour in ten is expected to come in below `pv_estimate10`, and one in ten
above `pv_estimate90`. The width of that range comes from how far your own
station's solar sensor has landed from the forecast (a station without a
sensor borrows the width measured at other stations). At night, and on a
forecast from before Pro Weather served the range, both equal
`pv_estimate`.

## What "corrected" means

Pro Weather fetches the solar radiation forecast from several weather models
and checks each against what your station's solar sensor measured. **On**
means that has run long enough (about two days) that the models your sky
favours get more say. **Off** means every model counts the same: the station
has no solar sensor, or it has not been scored yet. The forecast works
either way; corrected is usually closer.

What no forecast here knows: shade from trees or chimneys, snow on the
panels, or dirty glass.

## Privacy

The integration talks to `https://pro-weather.com/api/solar` only, with your
token in an `Authorization` header. The token is never logged, and the
diagnostics download redacts it.

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

## License

MIT
