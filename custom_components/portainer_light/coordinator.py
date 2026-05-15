"""Data Update Coordinator for Portainer Light."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
import json
import logging
from typing import Any

from pyportainer import (
    EndpointStatus,
    Portainer,
    PortainerAuthenticationError,
    PortainerConnectionError,
    PortainerTimeoutError,
)
from pyportainer.models.portainer import Endpoint

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_MODE_GLOBAL,
    SERVICE_MODE_REPLICATED,
)

type PortainerLightConfigEntry = ConfigEntry[PortainerLightCoordinator]

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PortainerLightServiceData:
    """Data for a single Docker Swarm service."""

    id: str
    name: str
    mode: str
    replicas: int
    spec: dict[str, Any]
    version_index: int


@dataclass
class PortainerLightEndpointData:
    """Data for a single Portainer endpoint."""

    id: int
    name: str | None
    endpoint: Endpoint
    services: dict[str, PortainerLightServiceData]


class PortainerLightCoordinator(
    DataUpdateCoordinator[dict[int, PortainerLightEndpointData]]
):
    """Data Update Coordinator for Portainer Light."""

    config_entry: PortainerLightConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: PortainerLightConfigEntry,
        portainer: Portainer,
    ) -> None:
        """Initialize the Portainer Light coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.portainer = portainer

        self.known_endpoints: set[int] = set()
        self.known_services: set[tuple[int, str]] = set()

        self.new_endpoints_callbacks: list[
            Callable[[list[PortainerLightEndpointData]], None]
        ] = []
        self.new_services_callbacks: list[
            Callable[
                [
                    list[
                        tuple[PortainerLightEndpointData, PortainerLightServiceData]
                    ]
                ],
                None,
            ]
        ] = []

    async def _async_setup(self) -> None:
        """Validate connection on first setup."""
        try:
            await self.portainer.get_endpoints()
        except PortainerAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
                translation_placeholders={"error": repr(err)},
            ) from err
        except PortainerConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": repr(err)},
            ) from err
        except PortainerTimeoutError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="timeout_connect",
                translation_placeholders={"error": repr(err)},
            ) from err

    async def _async_update_data(self) -> dict[int, PortainerLightEndpointData]:
        """Fetch swarm services from each endpoint."""
        _LOGGER.debug(
            "Fetching swarm services from Portainer: %s",
            self.config_entry.data[CONF_URL],
        )

        try:
            endpoints = await self.portainer.get_endpoints()
        except PortainerAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
                translation_placeholders={"error": repr(err)},
            ) from err
        except PortainerConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": repr(err)},
            ) from err

        mapped: dict[int, PortainerLightEndpointData] = {}

        for endpoint in endpoints:
            if endpoint.status == EndpointStatus.DOWN:
                _LOGGER.debug(
                    "Skipping offline endpoint: %s (ID: %d)",
                    endpoint.name,
                    endpoint.id,
                )
                continue

            try:
                services = await self._fetch_services(endpoint.id)
            except PortainerAuthenticationError as err:
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key="invalid_auth",
                    translation_placeholders={"error": repr(err)},
                ) from err
            except PortainerConnectionError as err:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="cannot_connect",
                    translation_placeholders={"error": repr(err)},
                ) from err

            mapped[endpoint.id] = PortainerLightEndpointData(
                id=endpoint.id,
                name=endpoint.name,
                endpoint=endpoint,
                services=services,
            )

        self._async_add_remove(mapped)

        return mapped

    async def _fetch_services(
        self, endpoint_id: int
    ) -> dict[str, PortainerLightServiceData]:
        """Fetch swarm services (Replicated + Global) for an endpoint."""
        raw_services: list[dict[str, Any]] = await self.portainer._request(  # noqa: SLF001
            f"endpoints/{endpoint_id}/docker/services"
        )

        replicated: dict[str, PortainerLightServiceData] = {}
        globals_pending: dict[str, PortainerLightServiceData] = {}

        for raw in raw_services:
            spec = raw.get("Spec") or {}
            mode = spec.get("Mode") or {}
            service_id = raw.get("ID")
            name = spec.get("Name")
            version_index = (raw.get("Version") or {}).get("Index", 0)

            if not service_id or not name:
                continue

            if "Replicated" in mode:
                replicas = (mode["Replicated"] or {}).get("Replicas", 0)
                replicated[service_id] = PortainerLightServiceData(
                    id=service_id,
                    name=name,
                    mode=SERVICE_MODE_REPLICATED,
                    replicas=int(replicas) if replicas is not None else 0,
                    spec=spec,
                    version_index=int(version_index),
                )
            elif "Global" in mode:
                globals_pending[service_id] = PortainerLightServiceData(
                    id=service_id,
                    name=name,
                    mode=SERVICE_MODE_GLOBAL,
                    replicas=0,
                    spec=spec,
                    version_index=int(version_index),
                )

        if globals_pending:
            running_per_service = await self._fetch_running_tasks(endpoint_id)
            for service_id, data in globals_pending.items():
                data.replicas = running_per_service.get(service_id, 0)

        return {**replicated, **globals_pending}

    async def _fetch_running_tasks(self, endpoint_id: int) -> dict[str, int]:
        """Count running tasks per ServiceID for the given endpoint."""
        try:
            tasks: list[dict[str, Any]] = await self.portainer._request(  # noqa: SLF001
                f"endpoints/{endpoint_id}/docker/tasks",
                params={"filters": json.dumps({"desired-state": ["running"]})},
            )
        except PortainerTimeoutError:
            _LOGGER.warning(
                "Timeout fetching swarm tasks for endpoint %s; "
                "Global replica counts will be 0 this cycle",
                endpoint_id,
            )
            return {}

        counter: Counter[str] = Counter()
        for task in tasks:
            service_id = task.get("ServiceID")
            if service_id:
                counter[service_id] += 1
        return dict(counter)

    def _async_add_remove(
        self, mapped: dict[int, PortainerLightEndpointData]
    ) -> None:
        """Fire callbacks for newly discovered endpoints and services."""
        current_endpoints = set(mapped)
        self.known_endpoints &= current_endpoints
        new_endpoint_ids = current_endpoints - self.known_endpoints
        if new_endpoint_ids:
            _LOGGER.debug("New endpoints found: %s", new_endpoint_ids)
            self.known_endpoints.update(new_endpoint_ids)
            new_endpoints = [mapped[eid] for eid in new_endpoint_ids]
            for cb in self.new_endpoints_callbacks:
                cb(new_endpoints)

        current_services = {
            (endpoint.id, service_id)
            for endpoint in mapped.values()
            for service_id in endpoint.services
        }
        self.known_services &= current_services
        new_service_keys = current_services - self.known_services
        if new_service_keys:
            _LOGGER.debug("New services found: %s", new_service_keys)
            self.known_services.update(new_service_keys)
            new_services = [
                (mapped[endpoint_id], mapped[endpoint_id].services[service_id])
                for endpoint_id, service_id in new_service_keys
            ]
            for cb in self.new_services_callbacks:
                cb(new_services)
