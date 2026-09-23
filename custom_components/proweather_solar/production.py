"""Send the panels' measured energy per hour to Pro Weather.

POST /api/solar/production teaches the site a production scale (shade and
soiling the station's solar sensor cannot see), which GET /api/solar then
applies. The source is Home Assistant's own hourly long-term statistics for
the sensor the user picked, the same numbers the Energy dashboard shows:
`change` already handles meter resets and unit conversion, so this module
never has to difference raw states itself.

Every run sends the last UPLOAD_HOURS finished hours. The API overwrites an
hour it already has, so resending is harmless and an hour missed while Home
Assistant or the network was down is filled in by the next run.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

UPLOAD_HOURS = 24
# Hourly long-term statistics are compiled a few minutes after the hour;
# :15 is safely after that and away from the top-of-hour rush.
UPLOAD_MINUTE = 15


def hours_from_statistics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recorder hourly rows (start as a UTC timestamp, change in Wh) to the
    API's {"start", "wh"} list. An hour without a change (no data) is left
    out rather than sent as 0, which the scale would read as an outage; a
    negative change is a meter swap the statistics could not bridge."""
    out = []
    for row in rows:
        change = row.get("change")
        if change is None or change < 0:
            continue
        start = datetime.fromtimestamp(row["start"], UTC)
        out.append({"start": start.isoformat().replace("+00:00", "Z"), "wh": round(change, 1)})
    return out


async def _hourly_statistics(hass: HomeAssistant, entity_id: str, start: datetime, end: datetime):
    # Imported here so a Home Assistant without the recorder still loads the
    # integration; only the upload needs it.
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.statistics import statistics_during_period

    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {entity_id},
        "hour",
        {"energy": "Wh"},
        {"change"},
    )
    return stats.get(entity_id, [])


async def async_upload(
    session: aiohttp.ClientSession, base_url: str, token: str, hours: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """One POST. Returns the API's answer, or None after logging why not.

    Never raises: a failed upload is retried by the next hourly run, which
    resends the whole trailing day. Log lines carry the status and the API's
    own message, never the token (it is in a header, not the URL)."""
    try:
        async with asyncio.timeout(30):
            async with session.post(
                f"{base_url.rstrip('/')}/api/solar/production",
                headers={"Authorization": f"Bearer {token}"},
                json={"hours": hours},
            ) as resp:
                try:
                    body = await resp.json()
                except aiohttp.ContentTypeError, ValueError:
                    body = {}
                if resp.status == 200:
                    return body
                message = body.get("error", "") if isinstance(body, dict) else ""
                # 400 means the sensor is wrong (for example a whole-house
                # meter, or kWh stored as Wh): worth the user's attention.
                level = logging.WARNING if resp.status in (400, 409) else logging.DEBUG
                _LOGGER.log(level, "Production upload refused: HTTP %s %s", resp.status, message)
    except (TimeoutError, aiohttp.ClientError) as err:
        _LOGGER.debug("Production upload failed: %s", type(err).__name__)
    return None


async def async_upload_production(
    hass: HomeAssistant, base_url: str, token: str, entity_id: str
) -> dict[str, Any] | None:
    """Send the last UPLOAD_HOURS finished hours of `entity_id`."""
    end = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    rows = await _hourly_statistics(hass, entity_id, end - timedelta(hours=UPLOAD_HOURS), end)
    hours = hours_from_statistics(rows)
    if not hours:
        _LOGGER.debug("No hourly statistics for %s yet", entity_id)
        return None
    return await async_upload(async_get_clientsession(hass), base_url, token, hours)
