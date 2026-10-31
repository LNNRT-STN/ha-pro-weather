import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.proweather_solar.const import DOMAIN
from custom_components.proweather_solar.station import parse_station

from .conftest import VIEW_URL, make_view

RESOLVE_URL = "https://pro-weather.com/api/v1/resolve?host=weer.example.be"


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("ardooie", ("ardooie", None)),
        (" Ardooie.pro-weather.com ", ("ardooie", None)),
        ("https://ardooie.pro-weather.com/history?range=7d", ("ardooie", None)),
        ("pro-weather.com/s/ardooie", ("ardooie", None)),
        ("https://www.pro-weather.com/s/ardooie/", ("ardooie", None)),
        ("https://weer.example.be/", (None, "weer.example.be")),
        ("a.b.pro-weather.com", (None, None)),
        ("pro-weather.com", (None, None)),
        ("", (None, None)),
    ],
)
def test_parse_station(typed, expected):
    assert parse_station(typed) == expected


async def _station(hass, typed):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "station"}
    )
    assert result["step_id"] == "station"
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"subdomain": typed})


async def test_platform_address(hass, aioclient_mock):
    aioclient_mock.get(VIEW_URL, json=make_view())
    result = await _station(hass, "https://ardooie.pro-weather.com/")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Weerstation Ardooie"
    assert result["data"] == {"subdomain": "ardooie"}
    assert result["result"].unique_id == "ardooie"


async def test_custom_domain_resolves(hass, aioclient_mock):
    aioclient_mock.get(RESOLVE_URL, json={"version": 1, "subdomain": "ardooie"})
    aioclient_mock.get(VIEW_URL, json=make_view())
    result = await _station(hass, "weer.example.be")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"subdomain": "ardooie"}


async def test_unknown_custom_domain(hass, aioclient_mock):
    aioclient_mock.get(RESOLVE_URL, status=404, json={"error": "Not found"})
    result = await _station(hass, "weer.example.be")
    assert result["errors"] == {"base": "not_found"}


async def test_unpublished_station(hass, aioclient_mock):
    aioclient_mock.get(VIEW_URL, status=404, json={"error": "Not found"})
    result = await _station(hass, "ardooie")
    assert result["errors"] == {"base": "not_found"}


async def test_not_an_address(hass, aioclient_mock):
    result = await _station(hass, "a.b.pro-weather.com")
    assert result["errors"] == {"base": "invalid_station"}
    assert not aioclient_mock.mock_calls


async def test_already_configured(hass, aioclient_mock, station_entry):
    station_entry.add_to_hass(hass)
    result = await _station(hass, "ardooie.pro-weather.com")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_station_has_no_options(hass, station):
    assert not station.supports_options
