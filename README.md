# Portainer Light — Home Assistant Custom Integration

Lightweight Home Assistant integration that exposes Docker Swarm services
managed through [Portainer](https://www.portainer.io/) as replica-count
sensors, the standalone containers next to them (`docker run` /
`docker compose`) as state sensors, plus a single service to scale the
Swarm services.

It is intentionally minimal: no stack/volume/image/CPU/RAM entities, no
buttons. One sensor per swarm service whose state is the number of desired
replicas, one sensor per standalone container whose state is its Docker
state, and one HA service to change the replicas.

## Features

- Pick which Portainer endpoints to add, both when setting up the integration
  and later from **Configure**. Deselected endpoints are removed.
- One device per Portainer endpoint, one sensor per Docker Swarm service.
- Sensor state = desired replicas (`Replicated`) or running tasks (`Global`).
- `mode` attribute (`replicated` / `global`) on each sensor.
- `running` attribute: tasks whose container is actually running, to spot a
  service that is down or crash-looping (see below).
- `image` / `image_digest` attributes: the image (`repo:tag`) each service runs and
  the digest Swarm pinned it to, e.g. to compare the tag with the latest release.
- One sensor per standalone container (not created by Swarm): state =
  Docker state (`running`, `exited`, `restarting`…), with its health and exit
  code as attributes (see below).
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

## Sensor attributes

| Attribute       | Description                                                                 |
|-----------------|-----------------------------------------------------------------------------|
| `endpoint_id`   | Portainer endpoint ID.                                                      |
| `endpoint_name` | Portainer endpoint name.                                                    |
| `service_name`  | Swarm service name (`stackname_servicename`).                               |
| `mode`          | `replicated` or `global`.                                                   |
| `running`       | Tasks Swarm wants running whose container is in the `running` state. `null` when the tasks request timed out. |
| `image`         | Image the service runs, as `repo:tag` (e.g. `jc21/nginx-proxy-manager:2.16.0`). |
| `image_digest`  | Digest Swarm pinned the image to at deploy time (`sha256:…`), or `null`.    |

The state is what Swarm *wants* (desired replicas); `running` is what it
*has*. A service whose container keeps failing still reports `1` as its state,
but `running` drops to `0`. For example, a template binary sensor that turns
on when a service is not running as it should:

```yaml
- binary_sensor:
    name: My service down
    device_class: problem
    delay_on: "00:02:00"
    state: >-
      {% set r = state_attr('sensor.myendpoint_mystack_myservice', 'running') %}
      {{ r is number and r < states('sensor.myendpoint_mystack_myservice') | int(0) }}
```

The `delay_on` skips the few seconds a container needs to start after a
scale action or an update.

## Standalone containers

Containers that are not Swarm tasks (no `com.docker.swarm.service.id` label),
typically the ones started with `docker compose` because they need something
Swarm does not support (`devices:`, `shm_size:`, …), get one sensor each.
It is identified by the container name, so it survives re-creating the
container. A container that disappears makes its sensor unavailable.

State (enum): `created`, `running`, `paused`, `restarting`, `removing`,
`exited` or `dead`.

| Attribute         | Description                                                        |
|-------------------|--------------------------------------------------------------------|
| `container_name`  | Container name.                                                    |
| `compose_project` | `com.docker.compose.project` label (`null` outside compose).       |
| `compose_service` | `com.docker.compose.service` label.                                |
| `image`           | Image the container runs.                                          |
| `status`          | Docker's human status, e.g. `Up 9 days (healthy)`.                 |
| `health`          | `healthy`, `unhealthy`, `starting`, or `null` without healthcheck. |
| `exit_code`       | Exit code when `exited` or `restarting`, else `null`.              |

A container is in trouble when it is `restarting` (crash loop), `dead`,
`unhealthy`, or `exited` with a non-zero exit code:

```yaml
- binary_sensor:
    name: My container down
    device_class: problem
    delay_on: "00:02:00"
    state: >-
      {% set e = 'sensor.myendpoint_mycontainer' %}
      {{ states(e) in ['restarting', 'dead']
         or state_attr(e, 'health') == 'unhealthy'
         or (is_state(e, 'exited') and state_attr(e, 'exit_code') not in [0, none]) }}
```

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

- Stack, volume and image entities; one entity per Swarm task container.
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
