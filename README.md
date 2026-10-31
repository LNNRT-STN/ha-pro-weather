# Pro Weather for Home Assistant

Two things from [Pro Weather](https://pro-weather.com) in Home Assistant:

- **Weather station**: any published Pro Weather station's readings, today's
  highs and lows, rain totals, official weather warnings and the forecast its
  site shows, as a weather entity and sensors. No account or token needed.
- **Solar forecast**: an hour-by-hour power forecast for your own solar
  panels, in the Energy dashboard, as sensors and in the shape Predbat reads.
  Needs a site on the Pro plan.

Add each one as its own entry; you can have several of both.

## Install

With [HACS](https://hacs.xyz):

1. HACS > the three-dot menu > **Custom repositories**.
2. Repository `https://github.com/LNNRT-STN/ha-pro-weather`, type
   **Integration**, then **Add**.
3. Search for **Pro Weather**, download it, and restart Home Assistant.

By hand: copy `custom_components/proweather_solar` into your Home Assistant
`config/custom_components/` folder and restart.

# Weather station

## Set up

**Settings > Devices & services > Add integration > Pro Weather > Weather
station**, and enter the station's address: `ardooie.pro-weather.com`, the
station's own domain, or just `ardooie`. It works for any published station,
yours or someone else's.

The entry reads the same data the station's page and the Pro Weather app
show, every 5 minutes (the station's own refresh), in the site's units.
Home Assistant converts them to yours. If the station is briefly unreachable
the last reading stays up instead of going unavailable.

## Entities

**Weather entity** with the station's readings now, and the daily and hourly
forecast its site shows. Where Pro Weather's Local Forecast Engine has run
for the station, the next 24 hours of temperatures are its, corrected
against what the station measured; the attribution says so.

**Sensors**: temperature, feels like, dew point, humidity, pressure, wind
speed, gust and direction, rain today, rain rate, solar radiation, UV index,
air quality index (in the standard the owner chose) and today's high and
low, each with when it was set. Off by default, enable them under the
device: strongest gust today, 3-hour pressure change, cloud base, wind run,
rain in the last 24 hours, this month, this year and this storm, Beaufort,
the last reading time and the forecast error (the engine's mean error over
the last days next to the raw models').

A sensor is only created for what the station measures: no UV sensor on a
station without one. Reload the entry after the station gains a sensor.

**Weather warning** turns on while an official MeteoAlarm (Europe) or NWS
(US) warning covers the station. Its attributes list each one, most severe
first: level (yellow, orange, red), category, the issuer's own event text,
onset, expiry and a link. `highest_level` is there for automations.

## Blueprints

| Blueprint | What it does | Import |
| --- | --- | --- |
| Rain starting | Acts when the station measures rain, or the coming hour's rain chance passes your limit while it is still dry, with a quiet period | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FLNNRT-STN%2Fha-pro-weather%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fproweather%2Frain_start.yaml) |
| High wind | Closes awnings or blinds when a gust passes your limit | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FLNNRT-STN%2Fha-pro-weather%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fproweather%2Fhigh_wind.yaml) |
| Freeze warning | Acts in the evening when tomorrow's forecast low is at or below your limit, and when the station drops below it | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FLNNRT-STN%2Fha-pro-weather%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fproweather%2Ffreeze_alert.yaml) |

Each one takes your own actions: a phone notification, a smart plug, a valve.

## Dashboard

[`dashboards/proweather_dashboard.yaml`](dashboards/proweather_dashboard.yaml)
is a one-page dashboard built from Home Assistant's own cards only: the
warning when there is one, the hourly and daily forecast, the readings and
48 hours of graphs. The file says how to paste it in.

# Solar forecast

The forecast comes from weather models scored against your own station's
solar sensor. It needs a Pro Weather site on the Pro plan with panels set up
under **Setup > Solar forecast**.

## Set up

1. In your Pro Weather dashboard, open **Setup > Solar forecast**, add your
   panel arrays if you have not yet, and copy the API token (it starts with
   `pws_`).
2. In Home Assistant: **Settings > Devices & services > Add integration >
   Pro Weather > Solar forecast**, and paste the token.

The token is checked with one request. The form tells you if the token is
unknown, the site is not on the Pro plan, or there are no panels to forecast
yet. If you regenerate the token later, Home Assistant asks for the new one.

**Options:** the update interval, 30 minutes by default and 15 at the least. A
new forecast arrives once an hour, so polling faster gains nothing. And,
optionally, your **Solar production sensor** (see below).

## Measured production

Pick the energy sensor that counts what your panels make, the one the Energy
dashboard uses for solar production, under **Configure** on the integration.
At quarter past every hour the integration reads Home Assistant's own hourly
statistics for it and sends the finished hours of the last day to
`https://pro-weather.com/api/solar/production`. Sending an hour again
replaces it, so an hour missed while Home Assistant or the network was down
is filled in on the next run. An hour with no data is not sent.

From those hours Pro Weather learns how much of the forecast your roof really
delivers: shade from trees and chimneys, and dirty panels, which the
station's solar sensor cannot see. After 24 good hours every forecast number
here includes it. The dashboard's **Setup > Solar forecast** shows the
number. It needs the recorder, which every standard Home Assistant has.

If Pro Weather refuses the numbers, the log says why (for example a
whole-house meter that reports more than your panels could make).

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

What the station's sensor cannot know: shade from trees or chimneys, snow on
the panels, or dirty glass. Sending your measured production (above) teaches
the forecast the shade and the dirt.

## Privacy

A weather station entry reads `https://pro-weather.com/api/v1/<station>/view`
(and `/api/v1/resolve` once, when you enter a custom domain). It sends
nothing about you or your home.

A solar forecast entry talks to `https://pro-weather.com/api/solar` only (and to
`/api/solar/production` when you picked a production sensor: your hourly
solar energy, nothing else), with your token in an `Authorization` header. The token is never logged, and the
diagnostics download redacts it.

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

## License

MIT
