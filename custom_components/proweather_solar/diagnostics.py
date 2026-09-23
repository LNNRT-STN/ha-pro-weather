"""Diagnostics download, with the token redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import ProWeatherConfigEntry

TO_REDACT = {"token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ProWeatherConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(entry.data, TO_REDACT),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "last_exception": repr(coordinator.last_exception) if coordinator.last_exception else None,
        # The response carries no secret (station name, array names and kWp,
        # the forecast), and support needs it to answer "why this number".
        "response": data.body if data else None,
        "merged_slot_count": len(data.slots) if data else 0,
    }
