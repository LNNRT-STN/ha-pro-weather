import json

from custom_components.proweather_solar.diagnostics import async_get_config_entry_diagnostics

from .conftest import TOKEN


# Called directly rather than through /api/diagnostics: the `setup` fixture
# freezes the clock, and HA's HTTP auth then rejects the test client's token.
async def test_token_redacted(hass, setup):
    diag = await async_get_config_entry_diagnostics(hass, setup)
    assert diag["entry"]["data"]["token"] == "**REDACTED**"
    assert TOKEN not in json.dumps(diag)
    assert diag["response"]["station"]["name"] == "Ardooie"
