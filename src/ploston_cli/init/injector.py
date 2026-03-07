"""Source Config Injector - Inject Ploston into Claude/Cursor config.

This module handles the injection of Ploston into the source application's
MCP configuration. Each imported MCP server is replaced with a dedicated
bridge entry using --expose for drop-in compatibility, plus a 'ploston'
entry that exposes Ploston workflows.

See: INIT_IMPORT_INJECT_AMENDMENT.md (DEC-141)
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import socket
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_RUNNER_NAME_RE = re.compile(r"[^a-z0-9-]")
_MAX_RUNNER_NAME_LEN = 32


def default_runner_name() -> str:
    """Return a sanitised hostname suitable for use as a runner name.

    Rules: lowercase, alphanumeric + hyphens only, max 32 chars.
    """
    raw = socket.gethostname().lower()
    return _RUNNER_NAME_RE.sub("-", raw)[:_MAX_RUNNER_NAME_LEN]


def sanitise_runner_name(name: str, warn: bool = True) -> str:
    """Sanitise an arbitrary string into a valid runner name.

    Args:
        name: Raw runner name (e.g. from --runner-name flag)
        warn: If True, log a warning when characters are changed

    Returns:
        Sanitised runner name (alphanumeric + hyphens, max 32 chars, lowercase)
    """
    sanitised = _RUNNER_NAME_RE.sub("-", name.lower())[:_MAX_RUNNER_NAME_LEN]
    if warn and sanitised != name:
        logger.warning(
            "Runner name %r contained invalid characters; sanitised to %r",
            name,
            sanitised,
        )
    return sanitised


def _resolve_ploston_command() -> str:
    """Resolve the absolute path to the ``ploston`` binary.

    GUI applications (Claude Desktop, Cursor) use a minimal PATH that
    typically excludes pyenv shims, virtualenvs, and other shell-injected
    directories.  Using the absolute path ensures the bridge command is
    found regardless of the caller's PATH.

    Falls back to the bare ``"ploston"`` name if ``shutil.which`` cannot
    locate the binary (e.g. running in a test environment).
    """
    return shutil.which("ploston") or "ploston"


def _bridge_entry(cp_url: str, expose: str, runner_name: str | None) -> dict:
    """Build a single mcpServers entry for a ploston bridge command.

    Args:
        cp_url: Control Plane URL
        expose: Value for --expose flag (server name or 'workflows')
        runner_name: Value for --runner flag, or None to omit it

    Returns:
        mcpServers entry dict: {command, args}
    """
    args: list[str] = ["bridge", "--url", cp_url, "--expose", expose]
    if runner_name:
        args += ["--runner", runner_name]
    return {"command": _resolve_ploston_command(), "args": args}


def inject_ploston_into_config(
    config_path: Path,
    imported_servers: list[str],
    cp_url: str = "http://localhost:8022",
    runner_name: str | None = None,
) -> Path:
    """Inject Ploston into a Claude/Cursor config file.

    Generates one bridge entry per imported server (--expose <server>
    --runner <runner_name>) plus a 'ploston' entry for workflows
    (--expose workflows). Original entries are preserved in
    _ploston_imported for easy restoration.

    Edge cases handled:
    - E-16: If a server is named 'ploston', its backup key is renamed to
      'ploston-original' and a warning is logged.
    - E-17: runner_name is sanitised to [a-z0-9-] with a warning if changed.
    - E-18: If runner_name is None (CP-native / no runner), default_runner_name()
      is used. Pass runner_name="" to explicitly omit --runner for CP-native servers.

    Args:
        config_path: Path to the config file
        imported_servers: List of server names that were imported
        cp_url: Control Plane URL
        runner_name: Runner name for --runner args. None uses default_runner_name().
                     Pass empty string "" to omit --runner entirely (E-18).

    Returns:
        Path to the backup file
    """
    # Resolve runner name
    # Empty string is the E-18 signal: CP-native servers, no runner needed
    if runner_name is None:
        effective_runner: str | None = default_runner_name()
    elif runner_name == "":
        effective_runner = None  # E-18: intentionally omit --runner
    else:
        effective_runner = sanitise_runner_name(runner_name)

    # Create backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = config_path.with_suffix(f".backup_{timestamp}.json")
    shutil.copy2(config_path, backup_path)

    # Load config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    mcp_servers = config.get("mcpServers", {})

    # Build _ploston_imported backup section from selected servers
    imported_section: dict[str, object] = {
        "_comment": "Original server definitions — managed by Ploston. "
        "Swap with mcpServers to restore direct access.",
    }
    for server_name in imported_servers:
        if server_name in mcp_servers:
            backup_key = server_name
            if server_name == "ploston":
                # E-16: avoid key collision with the new ploston workflows entry
                backup_key = "ploston-original"
                logger.warning(
                    "Server named 'ploston' found; backed up as 'ploston-original' "
                    "to avoid collision with the Ploston workflows entry."
                )
            imported_section[backup_key] = mcp_servers.pop(server_name)

    # Generate one bridge entry per selected server (skip 'ploston' — handled below)
    new_servers: dict[str, object] = {}
    for server_name in imported_servers:
        if server_name == "ploston":
            continue  # E-16: workflows entry replaces it below
        new_servers[server_name] = _bridge_entry(
            cp_url=cp_url,
            expose=server_name,
            runner_name=effective_runner,
        )

    # Always append the ploston workflows entry last
    # No --runner needed — workflows are served directly from CP
    new_servers["ploston"] = _bridge_entry(
        cp_url=cp_url,
        expose="workflows",
        runner_name=None,
    )

    # Preserve non-imported servers (user may have servers outside the selection)
    config["mcpServers"] = {**mcp_servers, **new_servers}
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

    def __init__(self, config_path: Path, cp_url: str = "http://localhost:8022"):
        """Initialize injector.

        Args:
            config_path: Path to the source config file
            cp_url: URL of the Control Plane
        """
        self.config_path = config_path
        self.cp_url = cp_url

    def inject(self, imported_servers: list[str], runner_name: str | None = None) -> Path:
        """Inject Ploston into the config.

        Args:
            imported_servers: Server names to inject bridge entries for
            runner_name: Runner name for --runner args. None uses default_runner_name().
                         Pass "" to omit --runner entirely (CP-native servers).
        """
        return inject_ploston_into_config(
            self.config_path,
            imported_servers,
            self.cp_url,
            runner_name=runner_name,
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
