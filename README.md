# Portainer Light — Home Assistant Custom Integration

Lightweight Home Assistant integration that exposes Docker Swarm services
managed through [Portainer](https://www.portainer.io/) as replica-count
sensors, plus a single service to scale them.

It is intentionally minimal: no container/stack/volume/CPU/RAM entities,
no buttons. Just one sensor per swarm service whose state is the number of
desired replicas, and one HA service to change that number.

## Features

- Pick which Portainer endpoints to add, both when setting up the integration
  and later from **Configure**. Deselected endpoints are removed.
- One device per Portainer endpoint, one sensor per Docker Swarm service.
- Sensor state = desired replicas (`Replicated`) or running tasks (`Global`).
- `mode` attribute (`replicated` / `global`) on each sensor.
- HA service `portainer_light.scale_service` to scale `Replicated` services.
- Polling every 60 seconds + immediate refresh after each scale action.

## Requirements

- Home Assistant 2024.11 or newer.
- A Portainer instance reachable from Home Assistant.
- A Portainer API access token (Portainer UI → **My account → Access tokens**).

## Installation

### HACS (recommended)

1. In HACS, open **Integrations**.
2. Three-dot menu → **Custom repositories**.
3. Add the repository URL with category **Integration**:

       https://github.com/asanchezed/homeassistant-portainer-light

4. Install **Portainer Light**.
5. Restart Home Assistant.

### Manual

1. Download or clone this repository:

       git clone https://github.com/asanchezed/homeassistant-portainer-light.git

2. Copy `custom_components/portainer_light/` into your Home Assistant
   configuration directory under `custom_components/portainer_light/`.
3. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Portainer Light**.
3. Provide:
   - **URL** of your Portainer instance (e.g. `https://portainer.local:9443`).
   - **API token**.
   - **Verify SSL** (disable only for self-signed certificates).
4. Select the **endpoints** you want to add. All of them are preselected.

A device is created per selected Portainer endpoint, and one sensor per Docker
Swarm service is registered under it. The sensor entity name follows the swarm
service name.

### Changing the endpoints later

**Settings → Devices & Services → Portainer Light → Configure** shows the same
endpoint list, with the current selection preselected. On save the integration
reloads, so:

- Endpoints you tick are added, with a sensor per swarm service.
- Endpoints you untick have their device — and therefore all of its sensors —
  removed from the registry.

Endpoints added to Portainer after the initial setup do not show up on their
own: open **Configure** and tick them.

## Service: `portainer_light.scale_service`

Scale a `Replicated` Docker Swarm service to a target number of replicas.
`Global` services and other modes are rejected.

| Field          | Type    | Required | Description                                              |
|----------------|---------|----------|----------------------------------------------------------|
| `device_id`    | string  | yes      | HA device ID of the **endpoint** to target.              |
| `service_name` | string  | yes      | Exact swarm service name (e.g. `stackname_servicename`). |
| `replicas`     | integer | yes      | Desired number of replicas. `0` stops the service.       |

Example:

```yaml
action: portainer_light.scale_service
data:
  device_id: <YOUR_ENDPOINT_DEVICE_ID>
  service_name: mystack_myservice
  replicas: 1
```

## Template switch example

The sensor is read-only. A common pattern is to wrap it in a template
switch so it can be toggled from the dashboard:

```yaml
- switch:
    name: My service
    icon: >-
      {% if states('sensor.myendpoint_mystack_myservice') | int(0) > 0 %}
        mdi:play-circle
      {% else %}
        mdi:stop-circle
      {% endif %}
    state: "{{ states('sensor.myendpoint_mystack_myservice') | int(0) > 0 }}"
    turn_on:
      - action: portainer_light.scale_service
        data:
          device_id: <YOUR_ENDPOINT_DEVICE_ID>
          service_name: mystack_myservice
          replicas: 1
    turn_off:
      - action: portainer_light.scale_service
        data:
          device_id: <YOUR_ENDPOINT_DEVICE_ID>
          service_name: mystack_myservice
          replicas: 0
```

## Out of scope

- Container, stack, volume, image entities.
- CPU/RAM stats.
- `prune_images`, container start/stop, kill, restart.
- Anything that the official Home Assistant `portainer` integration already
  covers — use that one instead if you need it.

## License and attribution

Licensed under the **Apache License, Version 2.0**. See [LICENSE](LICENSE).

This integration is a derivative work of the official `portainer` integration
shipped with [Home Assistant Core](https://github.com/home-assistant/core)
(`homeassistant/components/portainer/`), Copyright Home Assistant
Contributors, also licensed under Apache 2.0. See [NOTICE](NOTICE) for
attribution details.

## Disclaimer

This project is not affiliated with Portainer.io, the Home Assistant project,
or any of their respective contributors.
