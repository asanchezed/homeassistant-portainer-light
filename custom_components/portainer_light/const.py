"""Constants for the Portainer Light integration."""

from datetime import timedelta

DOMAIN = "portainer_light"
DEFAULT_NAME = "Portainer Light"

CONF_ENDPOINTS = "endpoints"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)

API_MAX_RETRIES = 3

SERVICE_MODE_REPLICATED = "replicated"
SERVICE_MODE_GLOBAL = "global"
