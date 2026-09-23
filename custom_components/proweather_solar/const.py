"""Constants for the Pro Weather solar forecast."""

DOMAIN = "proweather_solar"

CONF_BASE_URL = "base_url"
CONF_SCAN_INTERVAL = "scan_interval"
# The energy sensor (kWh, total_increasing) whose hourly statistics are sent
# to POST /api/solar/production. Unset = nothing is uploaded.
CONF_PRODUCTION_SENSOR = "production_sensor"

DEFAULT_BASE_URL = "https://pro-weather.com"
# Minutes. A new forecast lands once an hour (around :10 UTC), so polling
# faster than every 15 minutes only spends the 60 requests/hour per-IP budget
# the API allows, which a household may share with evcc or EMHASS.
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 15
