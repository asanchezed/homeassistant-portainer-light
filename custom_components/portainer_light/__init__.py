"""The Portainer Light integration."""

from __future__ import annotations

import logging

from pyportainer import Portainer

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import API_MAX_RETRIES, DOMAIN
from .coordinator import PortainerLightCoordinator, selected_endpoint_ids
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

    _async_remove_deselected_endpoints(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


@callback
def _async_remove_deselected_endpoints(
    hass: HomeAssistant, entry: PortainerLightConfigEntry
) -> None:
    """Drop devices (and their entities) of endpoints no longer selected."""
    selected = selected_endpoint_ids(entry)
    if selected is None:
        return

    device_reg = dr.async_get(hass)
    prefix = f"{entry.entry_id}_"

    for device in list(
        dr.async_entries_for_config_entry(device_reg, entry.entry_id)
    ):
        endpoint_ids = {
            int(identifier.removeprefix(prefix))
            for domain, identifier in device.identifiers
            if domain == DOMAIN
            and identifier.startswith(prefix)
            and identifier.removeprefix(prefix).isdigit()
        }
        if not endpoint_ids or endpoint_ids & selected:
            continue

        _LOGGER.debug(
            "Removing device %s: endpoint(s) %s are not selected",
            device.name,
            endpoint_ids,
        )
        device_reg.async_remove_device(device.id)


async def _async_options_updated(
    hass: HomeAssistant, entry: PortainerLightConfigEntry
) -> None:
    """Reload the entry so the endpoint selection is applied."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Portainer Light integration."""
    await async_setup_services(hass)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PortainerLightConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
