"""Source Config Injector - Inject Ploston into Claude/Cursor config.

This module handles the injection of Ploston into the source application's
MCP configuration, commenting out imported servers and adding the Ploston
proxy entry.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path


def inject_ploston_into_config(
    config_path: Path,
    imported_servers: list[str],
    cp_url: str = "http://localhost:8080",
) -> Path:
    """Inject Ploston into a Claude/Cursor config file.

    - Backs up the original config
    - Moves imported servers to _ploston_imported section
    - Adds ploston MCP server entry

    Args:
        config_path: Path to the config file
        imported_servers: List of server names that were imported
        cp_url: URL of the Control Plane

    Returns:
        Path to the backup file
    """
    # Create backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = config_path.with_suffix(f".backup_{timestamp}.json")
    shutil.copy2(config_path, backup_path)

    # Load config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    mcp_servers = config.get("mcpServers", {})

    # Move imported servers to _ploston_imported
    imported_section: dict[str, str | dict] = {
        "_comment": "These servers are now managed by Ploston. "
        "Remove this section to restore direct access.",
    }
    for server_name in imported_servers:
        if server_name in mcp_servers:
            imported_section[server_name] = mcp_servers.pop(server_name)

    # Add ploston entry
    mcp_servers["ploston"] = {
        "command": "npx",
        "args": ["-y", "@anthropic/mcp-proxy", cp_url],
    }

    # Update config
    config["mcpServers"] = mcp_servers
    config["_ploston_imported"] = imported_section

    # Write updated config
    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return backup_path


def restore_config_from_backup(config_path: Path, backup_path: Path) -> None:
    """Restore config from backup file.

    Args:
        config_path: Path to the config file to restore
        backup_path: Path to the backup file
    """
    shutil.copy2(backup_path, config_path)


def list_backups(config_path: Path) -> list[Path]:
    """List all backup files for a config.

    Args:
        config_path: Path to the original config file

    Returns:
        List of backup file paths, sorted by date (newest first)
    """
    pattern = f"{config_path.stem}.backup_*.json"
    backups = list(config_path.parent.glob(pattern))
    return sorted(backups, reverse=True)


def is_already_injected(config_path: Path) -> bool:
    """Check if Ploston is already injected into the config.

    Args:
        config_path: Path to the config file

    Returns:
        True if ploston entry exists in mcpServers
    """
    if not config_path.exists():
        return False

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        mcp_servers = config.get("mcpServers", {})
        return "ploston" in mcp_servers
    except (json.JSONDecodeError, OSError):
        return False


class SourceConfigInjector:
    """Manager for source config injection operations.

    Provides a class-based interface for injection management.
    """

    def __init__(self, config_path: Path, cp_url: str = "http://localhost:8080"):
        """Initialize injector.

        Args:
            config_path: Path to the source config file
            cp_url: URL of the Control Plane
        """
        self.config_path = config_path
        self.cp_url = cp_url

    def inject(self, imported_servers: list[str]) -> Path:
        """Inject Ploston into the config."""
        return inject_ploston_into_config(
            self.config_path,
            imported_servers,
            self.cp_url,
        )

    def restore(self, backup_path: Path) -> None:
        """Restore config from backup."""
        restore_config_from_backup(self.config_path, backup_path)

    def list_backups(self) -> list[Path]:
        """List all backups for this config."""
        return list_backups(self.config_path)

    @property
    def is_injected(self) -> bool:
        """Check if Ploston is already injected."""
        return is_already_injected(self.config_path)
