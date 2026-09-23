"""Client and polling for the Pro Weather solar forecast API (GET /api/solar)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BASE_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

type ProWeatherConfigEntry = ConfigEntry[ProWeatherCoordinator]


class ApiError(Exception):
    """Any failure talking to the API. `reason` is a config flow error key."""

    reason = "cannot_connect"


class InvalidAuth(ApiError):
    """401: missing, malformed or revoked token."""

    reason = "invalid_auth"


class PlanRequired(ApiError):
    """403: the site's plan does not include the solar forecast."""

    reason = "plan_required"


class NotSetUp(ApiError):
    """409: no panels set up, or the station has no location."""

    reason = "not_set_up"


class RateLimited(ApiError):
    """429: 60 requests per hour per IP."""

    reason = "rate_limited"


_STATUS_ERRORS: dict[int, type[ApiError]] = {
    401: InvalidAuth,
    403: PlanRequired,
    409: NotSetUp,
    429: RateLimited,
}


async def async_fetch(session: aiohttp.ClientSession, base_url: str, token: str) -> dict[str, Any]:
    """One GET /api/solar. Raises an ApiError subclass on anything but a 200.

    Error messages carry the status and the API's own `error` text only:
    the token is in a header, never in the URL, so nothing raised here can
    leak it into the log.
    """
    try:
        async with asyncio.timeout(30):
            async with session.get(
                f"{base_url.rstrip('/')}/api/solar",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                status = resp.status
                if status == 200:
                    return await resp.json()
                try:
                    message = (await resp.json()).get("error", "")
                except aiohttp.ContentTypeError, ValueError, AttributeError:
                    message = ""
    except (TimeoutError, aiohttp.ClientError) as err:
        raise ApiError(f"Cannot reach {base_url}: {type(err).__name__}") from None
    raise _STATUS_ERRORS.get(status, ApiError)(f"HTTP {status}: {message}".strip(": "))


@dataclass(frozen=True, slots=True)
class Slot:
    """One forecast hour."""

    start: datetime
    end: datetime
    watts: float  # mean AC power over the hour
    wh: float
    # The cautious and bright case, W: one hour in ten is expected below
    # `p10` and one above `p90`. The API sends them from engine 0.6.0; an
    # older response (or a night hour) has none, and both equal `watts`.
    p10: float
    p90: float


@dataclass
class SolarData:
    """The latest response plus the hours already past today.

    The API serves from the current issue forward, so after 10:00 it no
    longer has 08:00. `slots` keeps the earlier hours from previous polls, so
    "energy today" is the whole day (which is also what Predbat expects of a
    Solcast-style today sensor), not just what is left of it.
    """

    body: dict[str, Any]
    slots: list[Slot] = field(default_factory=list)

    @property
    def corrected(self) -> bool:
        return bool(self.body.get("corrected"))

    @property
    def issued_at(self) -> datetime | None:
        value = self.body.get("issuedAt")
        return dt_util.parse_datetime(value) if value else None

    def slot_at(self, when: datetime) -> Slot | None:
        return next((s for s in self.slots if s.start <= when < s.end), None)

    def slots_between(self, start: datetime, end: datetime) -> list[Slot]:
        """Slots that START in [start, end). An hour counts to the day it
        starts in, the same rule the API's `daily` uses."""
        return [s for s in self.slots if start <= s.start < end]

    def wh_between(self, start: datetime, end: datetime) -> float:
        return sum(s.wh for s in self.slots_between(start, end))

    def wh_remaining(self, now: datetime, end: datetime) -> float:
        """Energy from `now` until `end`, the current hour pro rata."""
        total = 0.0
        for s in self.slots:
            if s.end <= now or s.start >= end:
                continue
            if s.start < now:
                total += s.wh * (s.end - now) / (s.end - s.start)
            else:
                total += s.wh
        return total


def parse_slots(body: dict[str, Any]) -> list[Slot]:
    out = []
    for raw in body.get("slots") or []:
        start = dt_util.parse_datetime(raw.get("start", ""))
        end = dt_util.parse_datetime(raw.get("end", ""))
        if start is None or end is None:
            continue
        watts = float(raw.get("value") or 0)
        p10, p90 = raw.get("p10"), raw.get("p90")
        out.append(
            Slot(
                start,
                end,
                watts,
                float(raw.get("wh") or 0),
                watts if p10 is None else float(p10),
                watts if p90 is None else float(p90),
            )
        )
    return out


def merge_slots(old: list[Slot], new: list[Slot], now: datetime) -> list[Slot]:
    """New slots win; old ones survive only if the new response no longer
    covers their hour and they ended within the last 36 hours (enough for
    "today" in any time zone, including UTC-12 at 23:59)."""
    by_start = {s.start: s for s in old if s.end > now - timedelta(hours=36)}
    by_start.update({s.start: s for s in new})
    return sorted(by_start.values(), key=lambda s: s.start)


class ProWeatherCoordinator(DataUpdateCoordinator[SolarData]):
    """Polls the API; a failed poll keeps the last good data."""

    config_entry: ProWeatherConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ProWeatherConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self._session = async_get_clientsession(hass)
        self._base_url = entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)

    async def _async_update_data(self) -> SolarData:
        try:
            body = await async_fetch(self._session, self._base_url, self.config_entry.data["token"])
        except InvalidAuth as err:
            # Starts the reauth flow; the user pastes a new token there.
            raise ConfigEntryAuthFailed(str(err)) from err
        except ApiError as err:
            # 403, 409, 429, 503 and network errors: UpdateFailed. The base
            # class keeps `self.data`, the entities stay available on it
            # (entity.py), and the next poll retries.
            raise UpdateFailed(str(err)) from err
        old = self.data.slots if self.data else []
        return SolarData(body, merge_slots(old, parse_slots(body), dt_util.utcnow()))
