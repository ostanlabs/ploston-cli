"""Config Detector - Detect MCP configurations from Claude Desktop and Cursor.

This module provides platform-aware detection of MCP server configurations
from Claude Desktop and Cursor applications.
"""

from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ploston_core.config.secrets import SecretDetector

SourceType = Literal["claude_desktop", "cursor"]


@dataclass
class ServerInfo:
    """Information about a detected MCP server."""

    name: str
    source: SourceType
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"
    url: str | None = None

    # Environment variable availability
    env_vars_required: list[str] = field(default_factory=list)
    env_vars_available: dict[str, bool] = field(default_factory=dict)

    # Raw config for later use
    raw_config: dict[str, Any] = field(default_factory=dict)

    @property
    def all_env_vars_set(self) -> bool:
        """Check if all required env vars are set."""
        return all(self.env_vars_available.values()) if self.env_vars_available else True

    @property
    def display_command(self) -> str:
        """Get a display-friendly command string."""
        if self.command:
            args_str = " ".join(self.args[:2])
            if len(self.args) > 2:
                args_str += " ..."
            return f"{self.command} {args_str}".strip()
        elif self.url:
            return self.url
        return "(unknown)"


@dataclass
class DetectedConfig:
    """Result of detecting a config source."""

    source: SourceType
    path: Path
    servers: dict[str, ServerInfo] = field(default_factory=dict)
    server_count: int = 0
    error: str | None = None

    @property
    def found(self) -> bool:
        """Check if config was found and parsed successfully."""
        return self.error is None and self.server_count > 0


class ConfigDetector:
    """Detect MCP configurations from Claude Desktop and Cursor.

    Handles platform-specific config paths and directory scanning for Cursor.
    """

    # Config paths per platform
    CONFIG_PATHS: dict[SourceType, dict[str, str]] = {
        "claude_desktop": {
            "darwin": "~/Library/Application Support/Claude/claude_desktop_config.json",
            "linux": "~/.config/Claude/claude_desktop_config.json",
            "windows": "%APPDATA%\\Claude\\claude_desktop_config.json",
        },
        "cursor": {
            "darwin": "~/Library/Application Support/Cursor/User/globalStorage/cursor.mcp/",
            "linux": "~/.config/Cursor/User/globalStorage/cursor.mcp/",
            "windows": "%APPDATA%\\Cursor\\User\\globalStorage\\cursor.mcp\\",
        },
    }

    def __init__(self, secret_detector: SecretDetector | None = None):
        """Initialize detector.

        Args:
            secret_detector: SecretDetector instance for env var extraction
        """
        self.secret_detector = secret_detector or SecretDetector()
        self._platform = self._get_platform()

    def _get_platform(self) -> str:
        """Get normalized platform name."""
        system = platform.system().lower()
        if system == "darwin":
            return "darwin"
        elif system == "windows":
            return "windows"
        return "linux"

    def get_config_path(self, source: SourceType) -> Path | None:
        """Get the config path for a source on the current platform.

        Args:
            source: Source identifier ("claude_desktop" or "cursor")

        Returns:
            Expanded Path to config file/directory, or None if not configured
        """
        if source not in self.CONFIG_PATHS:
            return None

        path_str = self.CONFIG_PATHS[source].get(self._platform)
        if not path_str:
            return None

        # Expand ~ and environment variables
        path_str = os.path.expanduser(path_str)
        path_str = os.path.expandvars(path_str)
        return Path(path_str)

    def detect_all(self) -> list[DetectedConfig]:
        """Detect all MCP configurations on the current platform.

        Returns:
            List of DetectedConfig for each source (claude_desktop, cursor)
        """
        results = []
        for source in ["claude_desktop", "cursor"]:
            result = self.detect_source(source)  # type: ignore
            results.append(result)
        return results

    def detect_source(self, source: SourceType) -> DetectedConfig:
        """Detect MCP configuration from a specific source.

        Args:
            source: Source identifier

        Returns:
            DetectedConfig with servers or error
        """
        path = self.get_config_path(source)
        if path is None:
            return DetectedConfig(
                source=source,
                path=Path(""),
                error=f"No config path configured for {source} on {self._platform}",
            )

        if not path.exists():
            return DetectedConfig(
                source=source,
                path=path,
                error=f"Config not found at {path}",
            )

        try:
            if path.is_dir():
                # Cursor: scan directory for JSON files
                servers = self._scan_directory(source, path)
            else:
                # Claude Desktop: single file
                servers = self._parse_config_file(source, path)

            return DetectedConfig(
                source=source,
                path=path,
                servers=servers,
                server_count=len(servers),
            )
        except json.JSONDecodeError as e:
            return DetectedConfig(
                source=source,
                path=path,
                error=f"Invalid JSON: {e}",
            )
        except PermissionError:
            return DetectedConfig(
                source=source,
                path=path,
                error=f"Permission denied reading {path}",
            )
        except Exception as e:
            return DetectedConfig(
                source=source,
                path=path,
                error=str(e),
            )

    def _scan_directory(self, source: SourceType, directory: Path) -> dict[str, ServerInfo]:
        """Scan a directory for JSON config files (Cursor).

        Args:
            source: Source identifier
            directory: Directory to scan

        Returns:
            Dict of server name to ServerInfo
        """
        servers: dict[str, ServerInfo] = {}
        for json_file in directory.glob("*.json"):
            try:
                file_servers = self._parse_config_file(source, json_file)
                servers.update(file_servers)
            except (json.JSONDecodeError, PermissionError):
                # Skip invalid files
                continue
        return servers

    def _parse_config_file(self, source: SourceType, path: Path) -> dict[str, ServerInfo]:
        """Parse a single config file.

        Args:
            source: Source identifier
            path: Path to JSON file

        Returns:
            Dict of server name to ServerInfo
        """
        with open(path) as f:
            data = json.load(f)

        mcp_servers = data.get("mcpServers", {})
        servers: dict[str, ServerInfo] = {}

        for name, config in mcp_servers.items():
            server_info = self._parse_server_config(name, source, config)
            servers[name] = server_info

        return servers

    def _parse_server_config(
        self, name: str, source: SourceType, config: dict[str, Any]
    ) -> ServerInfo:
        """Parse a single server configuration.

        Args:
            name: Server name
            source: Source identifier
            config: Server configuration dict

        Returns:
            ServerInfo with parsed data
        """
        # Extract basic fields
        command = config.get("command")
        args = list(config.get("args", []))
        env = dict(config.get("env", {}))
        url = config.get("url")

        # Determine transport
        if command:
            transport = "stdio"
        elif url:
            transport = "http"
        else:
            transport = "stdio"

        # Extract required env vars (those using ${VAR} syntax or detected as secrets)
        env_vars_required: list[str] = []
        for key, value in env.items():
            if isinstance(value, str):
                # Check for ${VAR} references
                refs = self.secret_detector.extract_env_var_refs(value)
                env_vars_required.extend(refs)

                # Also check if the value itself looks like a secret
                if not refs:
                    detection = self.secret_detector.detect(key, value)
                    if detection:
                        env_vars_required.append(detection.suggested_env_var)

        # Check availability of env vars
        env_vars_available = {
            var: self.secret_detector.check_env_var_set(var) for var in env_vars_required
        }

        return ServerInfo(
            name=name,
            source=source,
            command=command,
            args=args,
            env=env,
            transport=transport,
            url=url,
            env_vars_required=env_vars_required,
            env_vars_available=env_vars_available,
            raw_config=config,
        )


def merge_configs(
    configs: list[DetectedConfig],
    priority_source: SourceType = "claude_desktop",
) -> dict[str, ServerInfo]:
    """Merge servers from multiple configs, deduplicating by name.

    Args:
        configs: List of detected configs
        priority_source: Source that takes priority on duplicates

    Returns:
        Dict of server name to ServerInfo (deduplicated)
    """
    merged: dict[str, ServerInfo] = {}

    # First pass: add all servers from non-priority sources
    for config in configs:
        if config.source != priority_source and config.found:
            for name, server in config.servers.items():
                merged[name] = server

    # Second pass: add/override with priority source
    for config in configs:
        if config.source == priority_source and config.found:
            for name, server in config.servers.items():
                merged[name] = server

    return merged
