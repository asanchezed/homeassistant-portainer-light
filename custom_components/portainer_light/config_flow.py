"""Config flow for the Portainer Light integration."""

from __future__ import annotations

import logging
from typing import Any

from pyportainer import (
    Portainer,
    PortainerAuthenticationError,
    PortainerConnectionError,
    PortainerTimeoutError,
)
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_ENDPOINTS, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Required(CONF_API_TOKEN): str,
        vol.Optional(CONF_VERIFY_SSL, default=True): bool,
    }
)


def _build_client(hass: HomeAssistant, data: dict[str, Any]) -> Portainer:
    """Build a Portainer client from config entry style data."""
    return Portainer(
        api_url=data[CONF_URL],
        api_key=data[CONF_API_TOKEN],
        session=async_get_clientsession(
            hass=hass, verify_ssl=data.get(CONF_VERIFY_SSL, True)
        ),
    )


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> str:
    """Validate the user input allows us to connect and return instance_id."""
    client = _build_client(hass, data)
    try:
        system_status = await client.portainer_system_status()
    except PortainerAuthenticationError:
        raise InvalidAuth from None
    except PortainerConnectionError as err:
        raise CannotConnect from err
    except PortainerTimeoutError as err:
        raise PortainerTimeout from err

    return system_status.instance_id


async def _async_endpoint_choices(
    hass: HomeAssistant, data: dict[str, Any]
) -> list[SelectOptionDict]:
    """Return the endpoints of a Portainer instance as selector options."""
    client = _build_client(hass, data)
    try:
        endpoints = await client.get_endpoints()
    except PortainerAuthenticationError:
        raise InvalidAuth from None
    except PortainerConnectionError as err:
        raise CannotConnect from err
    except PortainerTimeoutError as err:
        raise PortainerTimeout from err

    choices: list[SelectOptionDict] = []
    for endpoint in sorted(endpoints, key=lambda item: item.id):
        name = endpoint.name or f"Endpoint {endpoint.id}"
        choices.append(
            SelectOptionDict(value=str(endpoint.id), label=f"{name} (#{endpoint.id})")
        )
    return choices


def _endpoints_schema(
    choices: list[SelectOptionDict], selected: list[str] | None
) -> vol.Schema:
    """Build the multi-select schema used to pick the endpoints to add."""
    available = [choice["value"] for choice in choices]
    if selected is None:
        default = available
    else:
        default = [value for value in available if value in selected]

    return vol.Schema(
        {
            vol.Required(CONF_ENDPOINTS, default=default): SelectSelector(
                SelectSelectorConfig(
                    options=choices,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            )
        }
    )


class PortainerLightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Portainer Light."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._endpoint_choices: list[SelectOptionDict] = []

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> PortainerLightOptionsFlow:
        """Get the options flow for this handler."""
        return PortainerLightOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                instance_id = await _validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except PortainerTimeout:
                errors["base"] = "timeout_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(instance_id)
                self._abort_if_unique_id_configured()
                self._data = dict(user_input)
                return await self.async_step_endpoints()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_endpoints(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick which Portainer endpoints to add."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._data[CONF_URL],
                data=self._data,
                options={CONF_ENDPOINTS: user_input[CONF_ENDPOINTS]},
            )

        try:
            self._endpoint_choices = await _async_endpoint_choices(
                self.hass, self._data
            )
        except (CannotConnect, InvalidAuth, PortainerTimeout):
            return self.async_abort(reason="cannot_connect")

        if not self._endpoint_choices:
            return self.async_abort(reason="no_endpoints")

        return self.async_show_form(
            step_id="endpoints",
            data_schema=_endpoints_schema(self._endpoint_choices, None),
        )


class PortainerLightOptionsFlow(OptionsFlow):
    """Handle the reconfiguration of the endpoints exposed by the integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage which Portainer endpoints are exposed."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    CONF_ENDPOINTS: user_input[CONF_ENDPOINTS],
                }
            )

        try:
            choices = await _async_endpoint_choices(
                self.hass, dict(self.config_entry.data)
            )
        except (CannotConnect, InvalidAuth, PortainerTimeout):
            return self.async_abort(reason="cannot_connect")

        if not choices:
            return self.async_abort(reason="no_endpoints")

        return self.async_show_form(
            step_id="init",
            data_schema=_endpoints_schema(
                choices, self.config_entry.options.get(CONF_ENDPOINTS)
            ),
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class PortainerTimeout(HomeAssistantError):
    """Error to indicate a timeout occurred."""
