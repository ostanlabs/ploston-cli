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


def _bridge_entry(
    cp_url: str,
    expose: str | None = None,
    runner_name: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Build a single mcpServers entry for a ploston bridge command.

    Args:
        cp_url: Control Plane URL
        expose: Value for --expose flag (server name). Prefer ``tags`` for
                tag-based filtering; ``expose`` is still used for server-name
                expose (prefix stripping / session-map) and backward compat.
        runner_name: Value for --runner flag, or None to omit it
        tags: List of tag expressions forwarded via ``--tags`` flag.
              When provided, ``--expose`` is omitted in favour of ``--tags``.

    Returns:
        mcpServers entry dict: {command, args}
    """
    args: list[str] = ["bridge", "--url", cp_url]
    if tags:
        for tag in tags:
            args += ["--tags", tag]
    elif expose:
        args += ["--expose", expose]
    if runner_name:
        args += ["--runner", runner_name]
    return {"command": _resolve_ploston_command(), "args": args}


def inject_ploston_into_config(
    config_path: Path,
    imported_servers: list[str],
    cp_url: str = "http://localhost:8022",
    runner_name: str | None = None,
) -> None:
    """Inject Ploston into a Claude/Cursor config file.

    Generates one bridge entry per imported server (--expose <server>
    --runner <runner_name>) plus a 'ploston' entry for workflows
    (--expose workflows). Original entries are preserved in
    ``_ploston_imported`` inside the config JSON for inline rollback
    via :func:`restore_config_from_imported`.

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
    """
    # Resolve runner name
    # Empty string is the E-18 signal: CP-native servers, no runner needed
    if runner_name is None:
        effective_runner: str | None = default_runner_name()
    elif runner_name == "":
        effective_runner = None  # E-18: intentionally omit --runner
    else:
        effective_runner = sanitise_runner_name(runner_name)

    # Load config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    mcp_servers = config.get("mcpServers", {})

    # Build _ploston_imported backup section from selected servers.
    # Merge into any existing _ploston_imported so that incremental imports
    # (e.g. import 3 servers, then add a 4th) accumulate all originals for
    # correct rollback.
    imported_section: dict[str, object] = config.get("_ploston_imported", {})
    if not imported_section:
        imported_section = {}
    # Ensure the comment is always present
    imported_section["_comment"] = (
        "Original server definitions — managed by Ploston. "
        "Swap with mcpServers to restore direct access."
    )
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
            # Only back up if we don't already have a backup for this server
            # (preserve the earliest/original definition)
            if backup_key not in imported_section:
                imported_section[backup_key] = mcp_servers.pop(server_name)
            else:
                # Already backed up from a previous import — just remove from active
                mcp_servers.pop(server_name)

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

    # Append the authoring bridge (workflow management tools)
    new_servers["ploston-authoring"] = _bridge_entry(
        cp_url=cp_url,
        tags=["kind:workflow_mgmt"],
        runner_name=None,
    )

    # Append the workflows bridge (bare-name workflow execution tools)
    new_servers["ploston"] = _bridge_entry(
        cp_url=cp_url,
        tags=["kind:workflow"],
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


def restore_config_from_imported(config_path: Path) -> bool:
    """Restore config by swapping ``_ploston_imported`` back into ``mcpServers``.

    This is the fallback restore mechanism when no backup file exists on disk.
    It reads the inline ``_ploston_imported`` section (which always lives inside
    the config JSON), moves each original server definition back into
    ``mcpServers``, removes Ploston bridge entries, and deletes the
    ``_ploston_imported`` section.

    Args:
        config_path: Path to the config file to restore

    Returns:
        True if the config was successfully restored, False if there was
        nothing to restore (no ``_ploston_imported`` section found).
    """
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    imported = config.get("_ploston_imported")
    if not imported or not isinstance(imported, dict):
        return False

    mcp_servers = config.get("mcpServers", {})

    # Remove Ploston bridge entries (they all point to `ploston bridge ...`)
    bridge_keys = [name for name, entry in mcp_servers.items() if _is_ploston_bridge_entry(entry)]
    for key in bridge_keys:
        del mcp_servers[key]

    # Restore original server definitions from _ploston_imported
    for key, value in imported.items():
        if key.startswith("_"):
            continue  # skip metadata like _comment
        # Undo the E-16 rename: 'ploston-original' → 'ploston'
        restore_key = "ploston" if key == "ploston-original" else key
        mcp_servers[restore_key] = value

    config["mcpServers"] = mcp_servers
    del config["_ploston_imported"]

    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Restored config from inline _ploston_imported: %s", config_path)
    return True


def _is_ploston_bridge_entry(entry: object) -> bool:
    """Return True if *entry* looks like a Ploston bridge mcpServers entry."""
    if not isinstance(entry, dict):
        return False
    args = entry.get("args", [])
    if not isinstance(args, list):
        return False
    return len(args) >= 1 and args[0] == "bridge"


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

    def inject(self, imported_servers: list[str], runner_name: str | None = None) -> None:
        """Inject Ploston into the config.

        Args:
            imported_servers: Server names to inject bridge entries for
            runner_name: Runner name for --runner args. None uses default_runner_name().
                         Pass "" to omit --runner entirely (CP-native servers).
        """
        inject_ploston_into_config(
            self.config_path,
            imported_servers,
            self.cp_url,
            runner_name=runner_name,
        )

    def restore(self) -> bool:
        """Restore config from inline ``_ploston_imported`` section."""
        return restore_config_from_imported(self.config_path)

    @property
    def is_injected(self) -> bool:
        """Check if Ploston is already injected."""
        return is_already_injected(self.config_path)


# ---------------------------------------------------------------------------
# Shared injection helper (T-769)
# Used by: ploston init --inject, ploston inject, ploston server add --inject
# ---------------------------------------------------------------------------

SOURCE_LABELS: dict[str, str] = {
    "claude_desktop": "Claude Desktop",
    "cursor": "Cursor",
    "claude_code_global": "Claude Code (global)",
    "claude_code_project": "Claude Code (project)",
}


def run_injection(
    detected_configs: list,
    imported_servers: list[str],
    cp_url: str,
    runner_name: str | None = None,
    targets: list[str] | None = None,
) -> list[tuple[str, Path | None, str | None]]:
    """Shared injection logic for all callers.

    Args:
        detected_configs: List of DetectedConfig objects from ConfigDetector.detect_all()
        imported_servers: Server names to inject bridge entries for
        cp_url: Control Plane URL
        runner_name: Runner name for bridge entries
        targets: If given, only inject into these source types.
                 If None, inject into all detected configs.

    Returns:
        List of (source_type, path, error_or_none) for each attempted injection.
    """
    results: list[tuple[str, Path | None, str | None]] = []
    for detected in detected_configs:
        # Skip if targets are specified and this source is not in the list
        if targets and detected.source not in targets:
            continue
        # Skip if config was not found
        if not detected.found or not detected.path:
            continue
        try:
            inject_ploston_into_config(
                config_path=detected.path,
                imported_servers=imported_servers,
                cp_url=cp_url,
                runner_name=runner_name,
            )
            results.append((detected.source, detected.path, None))
        except Exception as e:
            results.append((detected.source, detected.path, str(e)))
    return results
