"""A Pro Weather station's public view (GET /api/v1/<subdomain>/view).

The same versioned payload the mobile app reads: current conditions, today's
highs and lows, rain totals, the forecast and official warnings, all in the
site's own units with a unit string beside every value. It is public (gated
like the station's own page, no token) and the server only ever adds fields
to v1, so every read below tolerates a missing key.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_SUBDOMAIN,
    DEFAULT_BASE_URL,
    DOMAIN,
    ROOT_DOMAIN,
    STATION_SCAN_INTERVAL,
)
from .coordinator import ApiError, async_get_json

_LOGGER = logging.getLogger(__name__)

type StationConfigEntry = ConfigEntry[StationCoordinator]

_SLUG = re.compile(r"^[a-z0-9-]{1,63}$")


def parse_station(text: str) -> tuple[str | None, str | None]:
    """What the user typed, as (subdomain, None) when it names a station
    directly, (None, host) when it is a custom domain the server must resolve,
    or (None, None) when it is neither.

    Accepts `ardooie`, `ardooie.pro-weather.com`, the path form
    `pro-weather.com/s/ardooie` and any of those as a full URL.
    """
    raw = text.strip().lower()
    parts = urlsplit(raw if "://" in raw else f"//{raw}")
    host = (parts.hostname or "").rstrip(".")
    if host in (ROOT_DOMAIN, f"www.{ROOT_DOMAIN}"):
        m = re.match(r"^/s/([^/]+)", parts.path)
        slug = m.group(1) if m else None
    elif host.endswith(f".{ROOT_DOMAIN}"):
        slug = host.removesuffix(f".{ROOT_DOMAIN}")
    elif "." not in host:
        slug = host
    else:
        return None, host
    return (slug, None) if slug and _SLUG.match(slug) else (None, None)


async def async_resolve_host(session: aiohttp.ClientSession, host: str) -> str:
    """A custom domain to its subdomain. Only a verified primary hostname
    resolves (404 otherwise), the same rule the server routes visitors by."""
    body = await async_get_json(
        session, f"{DEFAULT_BASE_URL}/api/v1/resolve?host={quote(host, safe='')}"
    )
    return body["subdomain"]


async def async_fetch_view(session: aiohttp.ClientSession, subdomain: str) -> dict[str, Any]:
    # range=24h, the smallest: the series it carries is the price of the one
    # payload that also has the 3h pressure and temperature trends.
    return await async_get_json(
        session, f"{DEFAULT_BASE_URL}/api/v1/{quote(subdomain)}/view?range=24h"
    )


class StationCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the view; a failed poll keeps the last good data."""

    config_entry: StationConfigEntry

    def __init__(self, hass: HomeAssistant, entry: StationConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=STATION_SCAN_INTERVAL),
        )
        self._session = async_get_clientsession(hass)
        self.subdomain: str = entry.data[CONF_SUBDOMAIN]

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await async_fetch_view(self._session, self.subdomain)
        except ApiError as err:
            # 404 (site unpublished or lapsed), 429, 503 and network errors.
            # No reauth: there is no credential to renew.
            raise UpdateFailed(str(err)) from err
