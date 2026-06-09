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

from ..shared.atomic import atomic_write_text

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
    bridge_name: str | None = None,
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
        bridge_name: Human-readable bridge display name for Grafana sessions.
              Emitted as ``--bridge-name`` so the Session Inspector can
              distinguish bridges from different agents (e.g.
              ``github/cursor`` vs ``github/claude-code``).

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
    if bridge_name:
        args += ["--bridge-name", bridge_name]
    return {"command": _resolve_ploston_command(), "args": args}


def _agent_label_from_source_id(source_id: str | None) -> str | None:
    """Derive a short, Grafana-friendly agent label from a source_id.

    Used to qualify bridge display names so that sessions from different
    agents are distinguishable in the Session Inspector.

    Examples::

        "cursor"                  → "cursor"
        "cursor_project"          → "cursor"
        "claude_desktop"          → "claude-desktop"
        "claude_code_global"      → "claude-code"
        "claude_code_project"     → "claude-code"
        "vscode_copilot_workspace"→ "copilot"
        "vscode_copilot_user"     → "copilot"
        "visual_studio_user"      → "vs"
        "windsurf"                → "windsurf"
        "gemini_cli_global"       → "gemini"
        "gemini_cli_project"      → "gemini"
        "cline"                   → "cline"
        "codex_global"            → "codex"
        "codex_project"           → "codex"
        "zed_user"                → "zed"
        "zed_project"             → "zed"
        None                      → None
    """
    if not source_id:
        return None
    label_map: dict[str, str] = {
        "cursor": "cursor",
        "cursor_project": "cursor",
        "claude_desktop": "claude-desktop",
        "claude_code_global": "claude-code",
        "claude_code_project": "claude-code",
        "windsurf": "windsurf",
        "gemini_cli_global": "gemini",
        "gemini_cli_project": "gemini",
        "cline": "cline",
        "vscode_copilot_workspace": "copilot",
        "vscode_copilot_user": "copilot",
        "visual_studio_user": "vs",
        "codex_global": "codex",
        "codex_project": "codex",
        "zed_user": "zed",
        "zed_project": "zed",
    }
    return label_map.get(source_id, source_id)


def inject_ploston_into_config(
    config_path: Path,
    imported_servers: list[str],
    cp_url: str = "http://localhost:8022",
    runner_name: str | None = None,
    no_backup_file: bool = False,
    source_id: str | None = None,
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
        source_id: Injection target identifier (e.g. "cursor", "claude_code_global").
                   When provided, derives a short agent label and emits
                   ``--bridge-name`` on each bridge entry so Grafana sessions
                   are agent-qualified (e.g. ``github/cursor``).
    """
    # Layer-2 backup (before any modification). Always taken first so the
    # pre-modification state is recoverable even if the steps below abort.
    if not no_backup_file:
        from .backup import make_backup

        make_backup(config_path)
    else:
        logger.warning(
            "Layer-2 file backup SKIPPED for %s (no_backup_file=True). "
            "Rollback will rely solely on the inline _ploston_imported section.",
            config_path,
        )

    # Resolve runner name
    # Empty string is the E-18 signal: CP-native servers, no runner needed
    if runner_name is None:
        effective_runner: str | None = default_runner_name()
    elif runner_name == "":
        effective_runner = None  # E-18: intentionally omit --runner
    else:
        effective_runner = sanitise_runner_name(runner_name)

    # FB-1 Defect-A guard #3: PROTECT THE READ. A malformed config must never
    # be overwritten — abort the target instead (the backup is already taken).
    try:
        raw = config_path.read_text(encoding="utf-8")
        config = json.loads(raw)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logger.error(
            "Refusing to inject into unreadable/malformed config %s: %s. File left untouched.",
            config_path,
            exc,
        )
        raise
    if not isinstance(config, dict):
        raise ValueError(f"Refusing to inject: {config_path} is not a JSON object. Left untouched.")
    mcp_servers = config.get("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        raise ValueError(
            f"Refusing to inject: 'mcpServers' in {config_path} is not an object. Left untouched."
        )

    # FB-1 Defect-A guard #2: EMPTY-LIST NO-OP. An empty server list must never
    # be allowed to collapse a config that already has user/bridge servers.
    existing_imported = config.get("_ploston_imported", {}) or {}
    has_existing_servers = bool(mcp_servers) or any(
        not k.startswith("_") for k in existing_imported
    )
    if not imported_servers and has_existing_servers:
        logger.warning(
            "No servers to inject for %s and the config already has servers; "
            "skipping injection (no-op) to avoid collapsing the config.",
            config_path,
        )
        return

    # Capture the pre-existing USER servers for the merge invariant (guard #1).
    # User servers = (live mcpServers minus recognized ploston bridge entries)
    #                UNION the originals already stashed in _ploston_imported.
    pre_user_servers: set[str] = {
        name for name, entry in mcp_servers.items() if not _is_ploston_bridge_entry(entry)
    }
    for key in existing_imported:
        if key.startswith("_"):
            continue
        # Undo the E-16 rename when accounting for the user-facing name.
        pre_user_servers.add("ploston" if key == "ploston-original" else key)

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

    # Derive agent label for --bridge-name so Grafana sessions show agent identity
    agent_label = _agent_label_from_source_id(source_id)

    def _make_bridge_name(friendly: str) -> str | None:
        """Compose ``{friendly}/{agent_label}`` when agent_label is known."""
        return f"{friendly}/{agent_label}" if agent_label else None

    # Generate one bridge entry per selected server (skip 'ploston' — handled below)
    new_servers: dict[str, object] = {}
    for server_name in imported_servers:
        if server_name == "ploston":
            continue  # E-16: workflows entry replaces it below
        new_servers[server_name] = _bridge_entry(
            cp_url=cp_url,
            expose=server_name,
            runner_name=effective_runner,
            bridge_name=_make_bridge_name(server_name),
        )

    # Append the authoring bridge (workflow management tools)
    new_servers["ploston-authoring"] = _bridge_entry(
        cp_url=cp_url,
        tags=["kind:workflow_mgmt"],
        runner_name=None,
        bridge_name=_make_bridge_name("workflow_mgmt"),
    )

    # Append the workflows bridge (bare-name workflow execution tools)
    new_servers["ploston"] = _bridge_entry(
        cp_url=cp_url,
        tags=["kind:workflow"],
        runner_name=None,
        bridge_name=_make_bridge_name("workflow"),
    )

    # Preserve non-imported servers (user may have servers outside the selection)
    merged_servers = {**mcp_servers, **new_servers}

    # FB-1 Defect-A guard #1: MERGE INVARIANT. The user-server set that remains
    # recoverable after this write (live non-bridge servers UNION the originals
    # in _ploston_imported) must be a SUPERSET of what existed before. If not,
    # we'd be silently shrinking the config — refuse to write.
    post_user_servers: set[str] = {
        name for name, entry in merged_servers.items() if not _is_ploston_bridge_entry(entry)
    }
    for key in imported_section:
        if key.startswith("_"):
            continue
        post_user_servers.add("ploston" if key == "ploston-original" else key)

    missing = pre_user_servers - post_user_servers
    if missing:
        raise ValueError(
            "Refusing to write a shrinking config for "
            f"{config_path}: user servers would be lost: {sorted(missing)}. "
            "File left untouched."
        )

    config["mcpServers"] = merged_servers
    config["_ploston_imported"] = imported_section

    # Write updated config (atomic: temp file + os.replace)
    atomic_write_text(
        config_path,
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

    # FB-1 guard #6: VERIFY-BEFORE-DESTROY. Take a fresh pre-restore backup so
    # the current (injected) state is never lost mid-restore. The backup helper
    # tags injected configs so this never becomes a canonical restore point.
    from .backup import make_backup

    make_backup(config_path)

    mcp_servers = config.get("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}

    # Remove Ploston bridge entries (they all point to `ploston bridge ...`)
    bridge_keys = [name for name, entry in mcp_servers.items() if _is_ploston_bridge_entry(entry)]
    for key in bridge_keys:
        del mcp_servers[key]

    # The user-facing server names we expect to recover from _ploston_imported.
    expected: set[str] = {
        ("ploston" if key == "ploston-original" else key)
        for key in imported
        if not key.startswith("_")
    }

    # Restore original server definitions from _ploston_imported
    for key, value in imported.items():
        if key.startswith("_"):
            continue  # skip metadata like _comment
        # Undo the E-16 rename: 'ploston-original' → 'ploston'
        restore_key = "ploston" if key == "ploston-original" else key
        mcp_servers[restore_key] = value

    # Verify the rebuilt config actually contains every expected server BEFORE
    # we destroy the inline backup. If anything is missing, abort without
    # deleting _ploston_imported (rollback remains possible).
    rebuilt = set(mcp_servers)
    if not expected.issubset(rebuilt):
        logger.error(
            "Aborting restore for %s: rebuilt config is missing %s; "
            "keeping _ploston_imported so rollback is still possible.",
            config_path,
            sorted(expected - rebuilt),
        )
        return False

    config["mcpServers"] = mcp_servers
    del config["_ploston_imported"]

    atomic_write_text(
        config_path,
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


def _build_source_labels() -> dict[str, str]:
    """Derive SOURCE_LABELS from TARGET_REGISTRY (single source of truth)."""
    from .injection_targets.registry import TARGET_REGISTRY

    return {sid: t.display_name for sid, t in TARGET_REGISTRY.items()}


SOURCE_LABELS: dict[str, str] = _build_source_labels()


def inject_via_target(
    source_id: str,
    config_path: Path,
    imported_servers: list[str],
    cp_url: str = "http://localhost:8022",
    runner_name: str | None = None,
    no_backup_file: bool = False,
) -> None:
    """Shape-aware injection using TARGET_REGISTRY dispatch.

    Looks up the InjectionTarget for *source_id* and uses its adapter to
    read/write the config in the correct shape. Falls back to the legacy
    ``inject_ploston_into_config`` for mcpServers-shape targets (same
    battle-tested code path).

    Args:
        source_id: Target identifier (e.g. "cursor", "vscode_copilot_workspace")
        config_path: Path to the config file
        imported_servers: Server names to inject bridge entries for
        cp_url: Control Plane URL
        runner_name: Runner name for --runner args
        no_backup_file: If True, skip Layer-2 backup creation.
    """
    from .injection_targets.adapters import McpServersAdapter
    from .injection_targets.registry import TARGET_REGISTRY

    target = TARGET_REGISTRY.get(source_id)
    if target is None or isinstance(target.adapter, McpServersAdapter):
        # Use the existing, battle-tested inject path for mcpServers shape
        inject_ploston_into_config(
            config_path=config_path,
            imported_servers=imported_servers,
            cp_url=cp_url,
            runner_name=runner_name,
            no_backup_file=no_backup_file,
            source_id=source_id,
        )
        return

    # Layer-2 backup (before any modification) for non-mcpServers shapes
    if not no_backup_file:
        from .backup import make_backup

        make_backup(config_path)
    else:
        logger.warning(
            "Layer-2 file backup SKIPPED for %s (no_backup_file=True).",
            config_path,
        )

    # Microsoft-shape (or future adapters): use adapter-based dispatch
    adapter = target.adapter

    # Resolve runner name
    if runner_name is None:
        effective_runner: str | None = default_runner_name()
    elif runner_name == "":
        effective_runner = None
    else:
        effective_runner = sanitise_runner_name(runner_name)

    # FB-1 guard #3: PROTECT THE READ — abort (do not overwrite) on a
    # malformed/unreadable config. Backup already taken above.
    try:
        data = adapter.read(config_path)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logger.error(
            "Refusing to inject into unreadable/malformed config %s: %s. File left untouched.",
            config_path,
            exc,
        )
        raise
    servers = adapter.get_servers(data)

    # FB-1 guard #2: EMPTY-LIST NO-OP for adapter shapes too.
    existing_backup_section = adapter.get_backup_section(data) or {}
    has_existing_servers = bool(servers) or any(
        not k.startswith("_") for k in existing_backup_section
    )
    if not imported_servers and has_existing_servers:
        logger.warning(
            "No servers to inject for %s and the config already has servers; "
            "skipping injection (no-op) to avoid collapsing the config.",
            config_path,
        )
        return

    # Capture pre-existing user servers for the merge invariant (guard #1).
    pre_user_servers: set[str] = {
        name for name, entry in servers.items() if not _is_ploston_bridge_entry(entry)
    }
    for key in existing_backup_section:
        if key.startswith("_"):
            continue
        pre_user_servers.add("ploston" if key == "ploston-original" else key)

    # Build backup section
    backup = adapter.get_backup_section(data)
    if not backup:
        backup = {}
    backup["_comment"] = (
        "Original server definitions — managed by Ploston. "
        "Swap with servers to restore direct access."
    )
    for server_name in imported_servers:
        if server_name in servers:
            backup_key = server_name
            if server_name == "ploston":
                backup_key = "ploston-original"
                logger.warning(
                    "Server named 'ploston' found; backed up as 'ploston-original' "
                    "to avoid collision with the Ploston workflows entry."
                )
            if backup_key not in backup:
                backup[backup_key] = servers.pop(server_name)
            else:
                servers.pop(server_name)

    # Derive agent label for --bridge-name so Grafana sessions show agent identity
    agent_label = _agent_label_from_source_id(source_id)

    def _make_bridge_name(friendly: str) -> str | None:
        return f"{friendly}/{agent_label}" if agent_label else None

    # Generate bridge entries using the target's make_ploston_entry,
    # then apply adapter-level decoration (e.g. "type": "stdio" for Microsoft).
    # S-313 / M-085: decorate_server_entry is the authoritative extension point.
    new_servers: dict[str, object] = {}
    for server_name in imported_servers:
        if server_name == "ploston":
            continue
        entry = target.make_ploston_entry(
            cp_url=cp_url,
            expose=server_name,
            runner_name=effective_runner,
            bridge_name=_make_bridge_name(server_name),
        )
        new_servers[server_name] = adapter.decorate_server_entry(entry)

    new_servers["ploston-authoring"] = adapter.decorate_server_entry(
        target.make_ploston_entry(
            cp_url=cp_url,
            tags=["kind:workflow_mgmt"],
            runner_name=None,
            bridge_name=_make_bridge_name("workflow_mgmt"),
        )
    )
    new_servers["ploston"] = adapter.decorate_server_entry(
        target.make_ploston_entry(
            cp_url=cp_url,
            tags=["kind:workflow"],
            runner_name=None,
            bridge_name=_make_bridge_name("workflow"),
        )
    )

    merged_servers = {**servers, **new_servers}

    # FB-1 guard #1: MERGE INVARIANT for adapter shapes.
    post_user_servers: set[str] = {
        name for name, entry in merged_servers.items() if not _is_ploston_bridge_entry(entry)
    }
    for key in backup:
        if key.startswith("_"):
            continue
        post_user_servers.add("ploston" if key == "ploston-original" else key)
    missing = pre_user_servers - post_user_servers
    if missing:
        raise ValueError(
            "Refusing to write a shrinking config for "
            f"{config_path}: user servers would be lost: {sorted(missing)}. "
            "File left untouched."
        )

    data = adapter.set_servers(data, merged_servers)
    data = adapter.set_backup_section(data, backup)
    adapter.write(config_path, data)


def run_injection(
    detected_configs: list,
    imported_servers: list[str],
    cp_url: str,
    runner_name: str | None = None,
    targets: list[str] | None = None,
    no_backup_file: bool = False,
) -> list[tuple[str, Path | None, str | None]]:
    """Shared injection logic for all callers.

    Uses TARGET_REGISTRY dispatch for shape-aware injection.

    Args:
        detected_configs: List of DetectedConfig objects from ConfigDetector.detect_all()
        imported_servers: Server names to inject bridge entries for
        cp_url: Control Plane URL
        runner_name: Runner name for bridge entries
        targets: If given, only inject into these source types.
                 If None, inject into all detected configs.
        no_backup_file: If True, skip Layer-2 backup creation.

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
            inject_via_target(
                source_id=detected.source,
                config_path=detected.path,
                imported_servers=imported_servers,
                cp_url=cp_url,
                runner_name=runner_name,
                no_backup_file=no_backup_file,
            )
            results.append((detected.source, detected.path, None))
        except Exception as e:
            results.append((detected.source, detected.path, str(e)))
    return results
