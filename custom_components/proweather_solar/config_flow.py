"""Config flow: paste the token, validated with one API call."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_BASE_URL,
    CONF_PRODUCTION_SENSOR,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .coordinator import ApiError, async_fetch

_LOGGER = logging.getLogger(__name__)

CONF_TOKEN = "token"
TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _clean_token(value: str) -> str:
    # People paste the whole header value from the REST sensor recipe.
    value = value.strip()
    return value[7:].strip() if value.lower().startswith("bearer ") else value


def _unique_id(token: str) -> str:
    # The API response names no site id, so the token's hash stands in for
    # one: the same token cannot be added twice, and the id reveals nothing.
    return hashlib.sha256(token.encode()).hexdigest()[:16]


class ProWeatherConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ProWeatherOptionsFlow:
        return ProWeatherOptionsFlow()

    async def _validate(self, token: str, base_url: str) -> tuple[dict | None, dict[str, str]]:
        try:
            body = await async_fetch(async_get_clientsession(self.hass), base_url, token)
        except ApiError as err:
            # str(err) is status + API message, never the token.
            _LOGGER.debug("Token check against %s failed: %s", base_url, err)
            return None, {"base": err.reason}
        return body, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = _clean_token(user_input[CONF_TOKEN])
            advanced = user_input.get("advanced", {})
            base_url = advanced.get(CONF_BASE_URL, DEFAULT_BASE_URL).strip().rstrip("/")
            await self.async_set_unique_id(_unique_id(token))
            self._abort_if_unique_id_configured()
            if not base_url.startswith(("https://", "http://")):
                errors["advanced"] = "invalid_url"
            else:
                body, errors = await self._validate(token, base_url)
            if not errors:
                station = (body or {}).get("station", {}).get("name") or "Pro Weather"
                return self.async_create_entry(
                    title=f"{station} solar",
                    data={CONF_TOKEN: token, CONF_BASE_URL: base_url},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_TOKEN): TOKEN_SELECTOR,
                # Collapsed, for pointing at staging or a local mock. A
                # section rather than show_advanced_options, which HA
                # deprecated (removal in 2027.6).
                vol.Optional("advanced"): section(
                    vol.Schema({vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str}),
                    {"collapsed": True},
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            entry = self._get_reauth_entry()
            token = _clean_token(user_input[CONF_TOKEN])
            _, errors = await self._validate(token, entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL))
            if not errors:
                # A regenerated token is a new hash; the entry keeps its
                # entities and takes the new unique id with it.
                return self.async_update_reload_and_abort(
                    entry, unique_id=_unique_id(token), data_updates={CONF_TOKEN: token}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): TOKEN_SELECTOR}),
            errors=errors,
        )


class ProWeatherOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            data: dict[str, Any] = {CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            if user_input.get(CONF_PRODUCTION_SENSOR):
                data[CONF_PRODUCTION_SENSOR] = user_input[CONF_PRODUCTION_SENSOR]
            return self.async_create_entry(data=data)
        options = self.config_entry.options
        current = options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        sensor = options.get(CONF_PRODUCTION_SENSOR)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=24 * 60,
                            step=1,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    # Optional and clearable: leaving it empty stops uploads.
                    vol.Optional(
                        CONF_PRODUCTION_SENSOR,
                        description={"suggested_value": sensor} if sensor else None,
                    ): EntitySelector(
                        EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.ENERGY)
                    ),
                }
            ),
        )
