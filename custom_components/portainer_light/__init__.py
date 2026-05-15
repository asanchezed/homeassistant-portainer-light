"""The Portainer Light integration."""

from __future__ import annotations

import logging

from pyportainer import Portainer

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import API_MAX_RETRIES, DOMAIN
from .coordinator import PortainerLightCoordinator
from .services import async_setup_services

_PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type PortainerLightConfigEntry = ConfigEntry[PortainerLightCoordinator]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: PortainerLightConfigEntry
) -> bool:
    """Set up Portainer Light from a config entry."""
    client = Portainer(
        api_url=entry.data[CONF_URL],
        api_key=entry.data[CONF_API_TOKEN],
        session=async_create_clientsession(
            hass=hass, verify_ssl=entry.data[CONF_VERIFY_SSL]
        ),
        request_timeout=30,
        max_retries=API_MAX_RETRIES,
    )

    coordinator = PortainerLightCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Portainer Light integration."""
    await async_setup_services(hass)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PortainerLightConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
