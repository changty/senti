"""Network policy management for sandbox containers."""

from __future__ import annotations

import logging

import docker
from docker.errors import APIError

logger = logging.getLogger(__name__)

# Allowlist networks and their allowed endpoints
NETWORK_POLICIES = {
    "senti_search_net": {
        "driver": "bridge",
        "internal": False,  # Needs external access for Brave API
    },
    "senti_gdrive_net": {
        "driver": "bridge",
        "internal": False,  # Needs access to Google APIs
    },
    "senti_email_net": {
        "driver": "bridge",
        "internal": False,  # Needs access to IMAP/SMTP
    },
}


def ensure_networks() -> None:
    """Create Docker networks if they don't exist."""
    client = docker.from_env()

    for name, config in NETWORK_POLICIES.items():
        try:
            client.networks.get(name)
            logger.debug("Network %s already exists", name)
        except docker.errors.NotFound:
            try:
                client.networks.create(
                    name=name,
                    driver=config["driver"],
                    internal=config.get("internal", True),
                )
                logger.info("Created network: %s", name)
            except APIError:
                logger.exception("Failed to create network: %s", name)
