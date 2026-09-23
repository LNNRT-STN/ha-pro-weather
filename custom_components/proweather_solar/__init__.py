"""Pro Weather solar forecast: the site's panel power forecast in Home Assistant."""

from __future__ import annotations

from datetime import datetime

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change

from .const import CONF_BASE_URL, CONF_PRODUCTION_SENSOR, DEFAULT_BASE_URL
from .coordinator import ProWeatherConfigEntry, ProWeatherCoordinator
from .production import UPLOAD_MINUTE, async_upload_production

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ProWeatherConfigEntry) -> bool:
    coordinator = ProWeatherCoordinator(hass, entry)
    # 401 raises ConfigEntryAuthFailed (reauth), anything else
    # ConfigEntryNotReady (HA retries the setup with backoff).
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    sensor = entry.options.get(CONF_PRODUCTION_SENSOR)
    if sensor:
        # The options flow reloads the entry, so a changed or cleared sensor
        # takes effect through this same path.
        async def _upload(_now: datetime) -> None:
            await async_upload_production(
                hass,
                entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                entry.data["token"],
                sensor,
            )

        entry.async_on_unload(
            async_track_time_change(hass, _upload, minute=UPLOAD_MINUTE, second=0)
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ProWeatherConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
