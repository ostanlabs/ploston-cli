"""CLI configuration management.

Handles persistent CLI configuration stored in ~/.ploston/config.yaml.
Supports environment variable overrides and CLI flag precedence.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Default values
DEFAULT_SERVER = "http://localhost:8082"
DEFAULT_TIMEOUT = 30
DEFAULT_OUTPUT_FORMAT = "table"

# Environment variable mappings
ENV_VARS = {
    "server": "PLOSTON_SERVER",
    "timeout": "PLOSTON_TIMEOUT",
    "output_format": "PLOSTON_OUTPUT_FORMAT",
}


@dataclass
class CLIConfig:
    """CLI configuration."""

    server: str = DEFAULT_SERVER
    timeout: int = DEFAULT_TIMEOUT
    output_format: str = DEFAULT_OUTPUT_FORMAT

    # Track where each value came from
    _sources: dict[str, str] = field(default_factory=dict)

    def get_source(self, key: str) -> str:
        """Get the source of a config value."""
        return self._sources.get(key, "default")


def get_config_path() -> Path:
    """Get the CLI config file path.

    Returns:
        Path to ~/.ploston/config.yaml
    """
    return Path.home() / ".ploston" / "config.yaml"


def load_config() -> CLIConfig:
    """Load CLI configuration.

    Precedence (highest to lowest):
    1. Environment variables
    2. Config file (~/.ploston/config.yaml)
    3. Defaults

    Returns:
        CLIConfig with values and sources
    """
    config = CLIConfig()
    sources: dict[str, str] = {}

    # Start with defaults
    for key in ["server", "timeout", "output_format"]:
        sources[key] = "default"

    # Load from config file
    config_path = get_config_path()
    if config_path.exists():
        try:
            with open(config_path) as f:
                file_config = yaml.safe_load(f) or {}

            if "server" in file_config:
                config.server = str(file_config["server"])
                sources["server"] = "config file"
            if "timeout" in file_config:
                config.timeout = int(file_config["timeout"])
                sources["timeout"] = "config file"
            if "output_format" in file_config:
                config.output_format = str(file_config["output_format"])
                sources["output_format"] = "config file"
        except Exception:
            pass  # Ignore config file errors, use defaults

    # Override with environment variables
    if os.environ.get(ENV_VARS["server"]):
        config.server = os.environ[ENV_VARS["server"]]
        sources["server"] = "environment"
    if os.environ.get(ENV_VARS["timeout"]):
        try:
            config.timeout = int(os.environ[ENV_VARS["timeout"]])
            sources["timeout"] = "environment"
        except ValueError:
            pass
    if os.environ.get(ENV_VARS["output_format"]):
        config.output_format = os.environ[ENV_VARS["output_format"]]
        sources["output_format"] = "environment"

    config._sources = sources
    return config


def save_config(key: str, value: Any) -> None:
    """Save a config value to the config file.

    Args:
        key: Config key (server, timeout, output_format)
        value: Value to save
    """
    config_path = get_config_path()

    # Load existing config
    existing: dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                existing = yaml.safe_load(f) or {}
        except Exception:
            pass

    # Update value
    existing[key] = value

    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write config
    with open(config_path, "w") as f:
        yaml.dump(existing, f, default_flow_style=False)


def unset_config(key: str) -> bool:
    """Remove a config value from the config file.

    Args:
        key: Config key to remove

    Returns:
        True if key was removed, False if not found
    """
    config_path = get_config_path()
    if not config_path.exists():
        return False

    try:
        with open(config_path) as f:
            existing = yaml.safe_load(f) or {}
    except Exception:
        return False

    if key not in existing:
        return False

    del existing[key]

    with open(config_path, "w") as f:
        yaml.dump(existing, f, default_flow_style=False)

    return True
