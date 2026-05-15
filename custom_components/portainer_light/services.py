"""Services for the Portainer Light integration."""

from __future__ import annotations

import json
import logging
from typing import Any

from pyportainer import (
    PortainerAuthenticationError,
    PortainerConnectionError,
    PortainerTimeoutError,
)
import voluptuous as vol

from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.service import async_extract_config_entry_ids

from .const import DOMAIN
from .coordinator import PortainerLightConfigEntry

_LOGGER = logging.getLogger(__name__)

ATTR_SERVICE_NAME = "service_name"
ATTR_REPLICAS = "replicas"

SERVICE_SCALE_SERVICE = "scale_service"
SERVICE_SCALE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_SERVICE_NAME): cv.string,
        vol.Required(ATTR_REPLICAS): vol.All(int, vol.Range(min=0)),
    }
)


async def _extract_config_entry(call: ServiceCall) -> PortainerLightConfigEntry:
    """Resolve the config entry behind the targeted device."""
    target_entry_ids = await async_extract_config_entry_ids(call)
    target_entries: list[PortainerLightConfigEntry] = [
        loaded
        for loaded in call.hass.config_entries.async_loaded_entries(DOMAIN)
        if loaded.entry_id in target_entry_ids
    ]
    if not target_entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_target",
        )
    return target_entries[0]


async def _get_endpoint_id(
    call: ServiceCall, config_entry: PortainerLightConfigEntry
) -> int:
    """Get the Portainer endpoint ID for the targeted device."""
    device_reg = dr.async_get(call.hass)
    device_id = call.data[ATTR_DEVICE_ID]
    device = device_reg.async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_target",
        )

    coordinator = config_entry.runtime_data
    for data in coordinator.data.values():
        if (
            DOMAIN,
            f"{config_entry.entry_id}_{data.endpoint.id}",
        ) in device.identifiers:
            return data.endpoint.id

    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="invalid_target",
    )


async def _scale_service(call: ServiceCall) -> None:
    """Scale a Docker Swarm service to the requested number of replicas."""
    config_entry = await _extract_config_entry(call)
    coordinator = config_entry.runtime_data
    endpoint_id = await _get_endpoint_id(call, config_entry)

    service_name: str = call.data[ATTR_SERVICE_NAME]
    replicas: int = call.data[ATTR_REPLICAS]

    try:
        services: list[dict[str, Any]] = await coordinator.portainer._request(  # noqa: SLF001
            f"endpoints/{endpoint_id}/docker/services",
            params={"filters": json.dumps({"name": [service_name]})},
        )

        matched = [
            svc
            for svc in services
            if (svc.get("Spec") or {}).get("Name") == service_name
        ]
        if not matched:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="service_not_found",
                translation_placeholders={"service_name": service_name},
            )

        service = matched[0]
        spec = service["Spec"]
        mode = spec.get("Mode") or {}
        if "Replicated" not in mode:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="service_not_replicated",
                translation_placeholders={"service_name": service_name},
            )

        spec["Mode"]["Replicated"]["Replicas"] = replicas

        await coordinator.portainer._request(  # noqa: SLF001
            f"endpoints/{endpoint_id}/docker/services/{service['ID']}/update",
            method="POST",
            params={"version": service["Version"]["Index"]},
            json_body=spec,
        )
    except PortainerAuthenticationError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="invalid_auth_no_details",
        ) from err
    except PortainerConnectionError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="cannot_connect_no_details",
        ) from err
    except PortainerTimeoutError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="timeout_connect_no_details",
        ) from err

    await coordinator.async_request_refresh()


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register Portainer Light services."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_SCALE_SERVICE,
        _scale_service,
        SERVICE_SCALE_SERVICE_SCHEMA,
    )
