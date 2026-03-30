"""Docker Compose generation for bootstrap command.

This module generates docker-compose.yaml files for deploying
the Ploston Control Plane stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Default paths
PLOSTON_DIR = Path.home() / ".ploston"

# Default registry and images
DEFAULT_REGISTRY = "ghcr.io/ostanlabs"
DEFAULT_PLOSTON_IMAGE = "ploston-dev"
DEFAULT_NATIVE_TOOLS_IMAGE = "native-tools-dev"
DEFAULT_NETWORK_NAME = "ploston-network"


@dataclass
class ComposeConfig:
    """Configuration for docker-compose generation."""

    tag: str = "latest"
    port: int = 8022
    redis_port: int = 6379
    with_observability: bool = False
    log_level: str = "INFO"
    firecrawl_key: str = ""
    registry: str = DEFAULT_REGISTRY
    ploston_image: str = DEFAULT_PLOSTON_IMAGE
    native_tools_image: str = DEFAULT_NATIVE_TOOLS_IMAGE
    output_dir: Path = field(default_factory=lambda: PLOSTON_DIR)
    # Network configuration
    network_name: str = DEFAULT_NETWORK_NAME
    network_external: bool = False  # If True, use existing network
    # Full image references (override registry/name/tag if set)
    ploston_image_full: str | None = None
    native_tools_image_full: str | None = None


class ComposeGenerator:
    """Generate docker-compose.yaml file."""

    def generate(self, config: ComposeConfig) -> Path:
        """Generate docker-compose.yaml in the output directory.

        Args:
            config: Configuration for compose generation.

        Returns:
            Path to the generated docker-compose.yaml file.
        """
        config.output_dir.mkdir(parents=True, exist_ok=True)
        compose_file = config.output_dir / "docker-compose.yaml"

        # Build compose structure
        compose_data = self._build_compose_dict(config)

        # Write to file with proper YAML formatting
        with open(compose_file, "w") as f:
            yaml.dump(compose_data, f, default_flow_style=False, sort_keys=False)

        return compose_file

    def _build_compose_dict(self, config: ComposeConfig) -> dict[str, Any]:
        """Build the docker-compose structure."""
        # Use full image references if provided, otherwise construct from parts
        ploston_image = (
            config.ploston_image_full or f"{config.registry}/{config.ploston_image}:{config.tag}"
        )
        native_tools_image = (
            config.native_tools_image_full
            or f"{config.registry}/{config.native_tools_image}:{config.tag}"
        )

        # Note: ploston image runs on port 8022 internally
        # We map host port (config.port) to container port 8022
        services: dict[str, Any] = {
            "ploston": {
                "image": ploston_image,
                "container_name": "ploston-cp",
                "ports": [f"{config.port}:8022"],
                "environment": {
                    "PLOSTON_HOST": "0.0.0.0",
                    "PLOSTON_LOG_LEVEL": config.log_level,
                    "PLOSTON_REDIS_URL": "redis://redis:6379/0",
                    "NATIVE_TOOLS_URL": "http://native-tools:8081",
                },
                "volumes": [
                    "./ploston-config.yaml:/etc/ploston/config.yaml:ro",
                    "./data/ploston:/app/data",
                    "./data/workflows:/app/workflows",
                ],
                "depends_on": {
                    "redis": {"condition": "service_healthy"},
                    "native-tools": {"condition": "service_started"},
                },
                "healthcheck": {
                    "test": ["CMD", "curl", "-f", "http://localhost:8022/health"],
                    "interval": "10s",
                    "timeout": "5s",
                    "retries": 5,
                    "start_period": "15s",
                },
                "restart": "unless-stopped",
            },
        }

        # When observability is enabled, inject OTEL env vars so the
        # ploston container forwards logs/traces to the collector (DEC-149).
        if config.with_observability:
            services["ploston"]["environment"].update(
                {
                    "PLOSTON_LOGS_ENABLED": "true",
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector:4317",
                    "OTEL_EXPORTER_OTLP_INSECURE": "true",
                }
            )

        services.update(
            {
                "native-tools": {
                    "image": native_tools_image,
                    "container_name": "ploston-native-tools",
                    "environment": {
                        "NATIVE_TOOLS_HOST": "0.0.0.0",
                        "NATIVE_TOOLS_PORT": "8081",
                        "REDIS_URL": "redis://redis:6379/0",
                        "FIRECRAWL_API_KEY": config.firecrawl_key or "",
                    },
                    "depends_on": {
                        "redis": {"condition": "service_healthy"},
                    },
                    "healthcheck": {
                        "test": ["CMD", "curl", "-f", "http://localhost:8081/health"],
                        "interval": "10s",
                        "timeout": "5s",
                        "retries": 5,
                        "start_period": "10s",
                    },
                    "restart": "unless-stopped",
                },
                "redis": {
                    "image": "redis:7-alpine",
                    "container_name": "ploston-redis",
                    "ports": [f"{config.redis_port}:6379"],
                    "volumes": ["./data/redis:/data"],
                    "command": "redis-server --appendonly yes --appendfsync everysec",
                    "healthcheck": {
                        "test": ["CMD", "redis-cli", "ping"],
                        "interval": "5s",
                        "timeout": "3s",
                        "retries": 5,
                    },
                    "restart": "unless-stopped",
                },
            }
        )

        # Build network configuration
        if config.network_external:
            # Use existing external network
            network_config: dict[str, Any] = {
                "default": {
                    "name": config.network_name,
                    "external": True,
                },
            }
        else:
            # Create new network
            network_config = {
                "default": {"name": config.network_name},
            }

        compose_data: dict[str, Any] = {
            "services": services,
            "networks": network_config,
        }

        return compose_data


class VolumeManager:
    """Manage data directories and seed configuration files."""

    def __init__(self, base_dir: Path | None = None):
        """Initialize volume manager.

        Args:
            base_dir: Base directory for Ploston data (default: ~/.ploston)
        """
        self.base_dir = base_dir or PLOSTON_DIR

    def setup_directories(self) -> list[Path]:
        """Create required data directories.

        Returns:
            List of created directory paths.
        """
        directories = [
            self.base_dir / "data" / "redis",
            self.base_dir / "data" / "ploston",
            self.base_dir / "data" / "workflows",
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

        return directories

    def generate_seed_config(self, overwrite: bool = False) -> Path | None:
        """Generate seed ploston-config.yaml if it doesn't exist.

        Args:
            overwrite: If True, overwrite existing config.

        Returns:
            Path to config file, or None if skipped.
        """
        config_file = self.base_dir / "ploston-config.yaml"

        if config_file.exists() and not overwrite:
            return None

        seed_config = {
            "version": "1.0",
            "mode": "configuration",
            "runners": {},
            "mcp_servers": {},
        }

        with open(config_file, "w") as f:
            yaml.dump(seed_config, f, default_flow_style=False, sort_keys=False)

        return config_file
