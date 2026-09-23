import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.proweather_solar.const import DOMAIN

from .conftest import TOKEN, URL, make_body


async def _start(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_success(hass, aioclient_mock):
    aioclient_mock.get(URL, json=make_body())
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    # A pasted "Bearer ..." header value is accepted too.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": f" Bearer {TOKEN} "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Ardooie solar"
    assert result["data"] == {"token": TOKEN, "base_url": "https://pro-weather.com"}
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, "invalid_auth"),
        (403, "plan_required"),
        (409, "not_set_up"),
        (429, "rate_limited"),
        (503, "cannot_connect"),
    ],
)
async def test_error_mapping(hass, aioclient_mock, caplog, status, error):
    caplog.set_level("DEBUG")
    aioclient_mock.get(URL, status=status, json={"error": "nope"})
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"token": TOKEN})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert TOKEN not in caplog.text


async def test_already_configured(hass, aioclient_mock, entry):
    from custom_components.proweather_solar.config_flow import _unique_id

    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, unique_id=_unique_id(TOKEN))
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"token": TOKEN})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert aioclient_mock.call_count == 0


async def test_advanced_base_url(hass, aioclient_mock):
    aioclient_mock.get("http://localhost:3000/api/solar", json=make_body())
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": TOKEN, "advanced": {"base_url": "http://localhost:3000/"}}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["base_url"] == "http://localhost:3000"


async def test_reauth(hass, aioclient_mock, setup):
    new = "pws_" + "cd" * 32
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, json=make_body())
    result = await setup.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"token": new})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert setup.data["token"] == new


async def test_options_interval(hass, setup):
    result = await hass.config_entries.options.async_init(setup.entry_id)
    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(result["flow_id"], {"scan_interval": 5})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 20}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup.options == {"scan_interval": 20}
    assert setup.runtime_data.update_interval.total_seconds() == 20 * 60


async def test_bad_base_url(hass, aioclient_mock):
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": TOKEN, "advanced": {"base_url": "pro-weather.com"}}
    )
    assert result["errors"] == {"advanced": "invalid_url"}
    assert aioclient_mock.call_count == 0
