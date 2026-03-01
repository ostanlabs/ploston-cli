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


@dataclass
class ComposeConfig:
    """Configuration for docker-compose generation."""

    tag: str = "latest"
    port: int = 8082
    redis_port: int = 6379
    with_observability: bool = False
    log_level: str = "INFO"
    firecrawl_key: str = ""
    registry: str = DEFAULT_REGISTRY
    ploston_image: str = DEFAULT_PLOSTON_IMAGE
    native_tools_image: str = DEFAULT_NATIVE_TOOLS_IMAGE
    output_dir: Path = field(default_factory=lambda: PLOSTON_DIR)


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
        ploston_image = f"{config.registry}/{config.ploston_image}:{config.tag}"
        native_tools_image = f"{config.registry}/{config.native_tools_image}:{config.tag}"

        services: dict[str, Any] = {
            "ploston": {
                "image": ploston_image,
                "container_name": "ploston-cp",
                "ports": [f"{config.port}:8082"],
                "environment": {
                    "PLOSTON_HOST": "0.0.0.0",
                    "PLOSTON_PORT": "8082",
                    "PLOSTON_LOG_LEVEL": config.log_level,
                    "REDIS_URL": "redis://redis:6379/0",
                    "NATIVE_TOOLS_URL": "http://native-tools:8081",
                },
                "volumes": [
                    "./ploston-config.yaml:/etc/ploston/config.yaml:ro",
                    "./data/ploston:/app/data",
                ],
                "depends_on": {
                    "redis": {"condition": "service_healthy"},
                    "native-tools": {"condition": "service_started"},
                },
                "healthcheck": {
                    "test": ["CMD", "curl", "-f", "http://localhost:8082/health"],
                    "interval": "10s",
                    "timeout": "5s",
                    "retries": 5,
                    "start_period": "15s",
                },
                "restart": "unless-stopped",
            },
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

        compose_data: dict[str, Any] = {
            "services": services,
            "networks": {
                "default": {"name": "ploston-network"},
            },
        }

        # Add observability services if requested
        if config.with_observability:
            self._add_observability_services(compose_data, config)

        return compose_data

    def _add_observability_services(
        self, compose_data: dict[str, Any], config: ComposeConfig
    ) -> None:
        """Add Prometheus, Grafana, and Loki services."""
        services = compose_data["services"]

        services["prometheus"] = {
            "image": "prom/prometheus:latest",
            "container_name": "ploston-prometheus",
            "ports": ["9090:9090"],
            "volumes": [
                "./prometheus.yml:/etc/prometheus/prometheus.yml:ro",
                "./data/prometheus:/prometheus",
            ],
            "command": [
                "--config.file=/etc/prometheus/prometheus.yml",
                "--storage.tsdb.path=/prometheus",
                "--web.enable-lifecycle",
            ],
            "restart": "unless-stopped",
        }

        services["grafana"] = {
            "image": "grafana/grafana:latest",
            "container_name": "ploston-grafana",
            "ports": ["3000:3000"],
            "environment": {
                "GF_SECURITY_ADMIN_PASSWORD": "admin",
                "GF_USERS_ALLOW_SIGN_UP": "false",
            },
            "volumes": [
                "./data/grafana:/var/lib/grafana",
                "./grafana/provisioning:/etc/grafana/provisioning:ro",
            ],
            "depends_on": ["prometheus", "loki"],
            "restart": "unless-stopped",
        }

        services["loki"] = {
            "image": "grafana/loki:latest",
            "container_name": "ploston-loki",
            "ports": ["3100:3100"],
            "volumes": [
                "./loki-config.yaml:/etc/loki/local-config.yaml:ro",
                "./data/loki:/loki",
            ],
            "command": "-config.file=/etc/loki/local-config.yaml",
            "restart": "unless-stopped",
        }


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
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

        return directories

    def setup_observability_directories(self) -> list[Path]:
        """Create directories for observability stack.

        Returns:
            List of created directory paths.
        """
        directories = [
            self.base_dir / "data" / "prometheus",
            self.base_dir / "data" / "grafana",
            self.base_dir / "data" / "loki",
            self.base_dir / "grafana" / "provisioning" / "datasources",
            self.base_dir / "grafana" / "provisioning" / "dashboards",
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

    def generate_prometheus_config(self, overwrite: bool = False) -> Path | None:
        """Generate prometheus.yml for scraping Ploston metrics.

        Args:
            overwrite: If True, overwrite existing config.

        Returns:
            Path to config file, or None if skipped.
        """
        config_file = self.base_dir / "prometheus.yml"

        if config_file.exists() and not overwrite:
            return None

        prometheus_config = {
            "global": {
                "scrape_interval": "15s",
                "evaluation_interval": "15s",
            },
            "scrape_configs": [
                {
                    "job_name": "ploston",
                    "static_configs": [{"targets": ["ploston:8082"]}],
                    "metrics_path": "/metrics",
                },
            ],
        }

        with open(config_file, "w") as f:
            yaml.dump(prometheus_config, f, default_flow_style=False, sort_keys=False)

        return config_file

    def generate_loki_config(self, overwrite: bool = False) -> Path | None:
        """Generate loki-config.yaml.

        Args:
            overwrite: If True, overwrite existing config.

        Returns:
            Path to config file, or None if skipped.
        """
        config_file = self.base_dir / "loki-config.yaml"

        if config_file.exists() and not overwrite:
            return None

        loki_config = {
            "auth_enabled": False,
            "server": {"http_listen_port": 3100},
            "common": {
                "path_prefix": "/loki",
                "storage": {
                    "filesystem": {
                        "chunks_directory": "/loki/chunks",
                        "rules_directory": "/loki/rules",
                    }
                },
                "replication_factor": 1,
                "ring": {"kvstore": {"store": "inmemory"}},
            },
            "schema_config": {
                "configs": [
                    {
                        "from": "2020-10-24",
                        "store": "boltdb-shipper",
                        "object_store": "filesystem",
                        "schema": "v11",
                        "index": {"prefix": "index_", "period": "24h"},
                    }
                ]
            },
        }

        with open(config_file, "w") as f:
            yaml.dump(loki_config, f, default_flow_style=False, sort_keys=False)

        return config_file
