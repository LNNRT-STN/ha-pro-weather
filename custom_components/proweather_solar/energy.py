"""Energy dashboard platform: offers this entry as a "Solar production
forecast" in Settings > Dashboards > Energy.

Contract (homeassistant/components/energy/types.py, EnergyPlatform, checked
against core `dev` on 2026-09-23): `async_get_solar_forecast(hass,
config_entry_id)` returns `{"wh_hours": {ISO timestamp: Wh}}` or None.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_solar_forecast(
    hass: HomeAssistant, config_entry_id: str
) -> dict[str, dict[str, float | int]] | None:
    entry = hass.config_entries.async_get_entry(config_entry_id)
    if entry is None or entry.domain != DOMAIN:
        return None
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None or coordinator.data is None:
        return None
    # From the merged slots rather than the response's own `wh_hours`, so the
    # hours already past today stay on the dashboard's forecast line.
    return {"wh_hours": {s.start.isoformat(): s.wh for s in coordinator.data.slots}}
