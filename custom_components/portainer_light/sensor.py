"""Sensor platform for the Portainer Light integration."""

from __future__ import annotations

import logging
from typing import Any

from yarl import URL

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONTAINER_STATES, DEFAULT_NAME, DOMAIN
from .coordinator import (
    PortainerLightConfigEntry,
    PortainerLightContainerData,
    PortainerLightCoordinator,
    PortainerLightEndpointData,
    PortainerLightServiceData,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PortainerLightConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Portainer Light sensors."""
    coordinator = entry.runtime_data
    device_reg = dr.async_get(hass)

    def _register_endpoint_devices(
        endpoints: list[PortainerLightEndpointData],
    ) -> None:
        """Register endpoint devices so scale_service can target them."""
        for endpoint in endpoints:
            device_reg.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={
                    (DOMAIN, f"{entry.entry_id}_{endpoint.id}"),
                },
                manufacturer=DEFAULT_NAME,
                model="Endpoint",
                name=endpoint.name or f"Endpoint {endpoint.id}",
                configuration_url=str(
                    URL(
                        f"{entry.data[CONF_URL]}#!/{endpoint.id}/docker/dashboard"
                    )
                ),
                entry_type=DeviceEntryType.SERVICE,
            )

    def _async_add_new_services(
        services: list[
            tuple[PortainerLightEndpointData, PortainerLightServiceData]
        ],
    ) -> None:
        """Add new service sensors."""
        async_add_entities(
            PortainerLightServiceSensor(coordinator, endpoint, service)
            for endpoint, service in services
        )

    def _async_add_new_containers(
        containers: list[
            tuple[PortainerLightEndpointData, PortainerLightContainerData]
        ],
    ) -> None:
        """Add new standalone container sensors."""
        async_add_entities(
            PortainerLightContainerSensor(coordinator, endpoint, container)
            for endpoint, container in containers
        )

    coordinator.new_endpoints_callbacks.append(_register_endpoint_devices)
    coordinator.new_services_callbacks.append(_async_add_new_services)
    coordinator.new_containers_callbacks.append(_async_add_new_containers)

    # Initial pass after first refresh
    _register_endpoint_devices(list(coordinator.data.values()))
    _async_add_new_services(
        [
            (endpoint, service)
            for endpoint in coordinator.data.values()
            for service in endpoint.services.values()
        ]
    )
    _async_add_new_containers(
        [
            (endpoint, container)
            for endpoint in coordinator.data.values()
            for container in endpoint.containers.values()
        ]
    )


class PortainerLightServiceSensor(
    CoordinatorEntity[PortainerLightCoordinator], SensorEntity
):
    """Sensor exposing the desired replica count of a Docker Swarm service."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:docker"

    def __init__(
        self,
        coordinator: PortainerLightCoordinator,
        endpoint: PortainerLightEndpointData,
        service: PortainerLightServiceData,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._endpoint_id = endpoint.id
        self._endpoint_name = endpoint.name
        self._service_id = service.id
        self._service_name = service.name

        entry = coordinator.config_entry
        self._attr_name = service.name
        self._attr_unique_id = (
            f"{entry.entry_id}_{endpoint.id}_{service.id}_replicas"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{endpoint.id}")},
        )

    @property
    def available(self) -> bool:
        """Return True if the service is still present in the coordinator data."""
        return (
            super().available
            and self._endpoint_id in self.coordinator.data
            and self._service_id
            in self.coordinator.data[self._endpoint_id].services
        )

    @property
    def _service_data(self) -> PortainerLightServiceData | None:
        endpoint = self.coordinator.data.get(self._endpoint_id)
        if endpoint is None:
            return None
        return endpoint.services.get(self._service_id)

    @property
    def native_value(self) -> StateType:
        """Return the desired replica count (or running tasks for Global)."""
        data = self._service_data
        if data is None:
            return None
        return data.replicas

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional info useful for automations and Lovelace."""
        data = self._service_data
        attrs: dict[str, Any] = {
            "endpoint_id": self._endpoint_id,
            "endpoint_name": self._endpoint_name,
            "service_name": self._service_name,
        }
        if data is not None:
            attrs["mode"] = data.mode
            # Tasks really running (None if the tasks call timed out). Compare
            # it with the state to spot a service that is down or crash-looping.
            attrs["running"] = data.running
        return attrs


class PortainerLightContainerSensor(
    CoordinatorEntity[PortainerLightCoordinator], SensorEntity
):
    """Sensor exposing the state of a standalone (non-Swarm) container."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = CONTAINER_STATES
    _attr_translation_key = "container"
    _attr_icon = "mdi:docker"

    def __init__(
        self,
        coordinator: PortainerLightCoordinator,
        endpoint: PortainerLightEndpointData,
        container: PortainerLightContainerData,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._endpoint_id = endpoint.id
        self._endpoint_name = endpoint.name
        self._container_name = container.name

        entry = coordinator.config_entry
        self._attr_name = container.name
        # By name, not by container ID: the ID changes every time the container
        # is re-created (docker compose up after a change, rm + up, ...).
        self._attr_unique_id = (
            f"{entry.entry_id}_{endpoint.id}_container_{container.name}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{endpoint.id}")},
        )

    @property
    def available(self) -> bool:
        """Return True if the container still exists in the coordinator data."""
        return (
            super().available
            and self._endpoint_id in self.coordinator.data
            and self._container_name
            in self.coordinator.data[self._endpoint_id].containers
        )

    @property
    def _container_data(self) -> PortainerLightContainerData | None:
        endpoint = self.coordinator.data.get(self._endpoint_id)
        if endpoint is None:
            return None
        return endpoint.containers.get(self._container_name)

    @property
    def native_value(self) -> StateType:
        """Return the Docker state (running, exited, restarting, ...)."""
        data = self._container_data
        if data is None or data.state not in CONTAINER_STATES:
            return None
        return data.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional info useful for automations and Lovelace."""
        data = self._container_data
        attrs: dict[str, Any] = {
            "endpoint_id": self._endpoint_id,
            "endpoint_name": self._endpoint_name,
            "container_name": self._container_name,
        }
        if data is not None:
            attrs.update(
                {
                    "compose_project": data.compose_project,
                    "compose_service": data.compose_service,
                    "image": data.image,
                    "status": data.status,
                    "health": data.health,
                    "exit_code": data.exit_code,
                }
            )
        return attrs
