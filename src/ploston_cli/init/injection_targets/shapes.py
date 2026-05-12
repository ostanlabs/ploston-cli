"""Config shape abstractions (S-315 / S-317, DEC-204).

ConfigShape owns structure: where servers live in the parsed data,
how the backup section is stored, and entry decoration.
Shape does not know or care how the data was serialized.

Internal API — not part of the public stability contract (DEC-206).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ConfigShape(Protocol):
    """Protocol for config structure operations."""

    def get_servers(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract the servers dict from the config data."""
        ...

    def set_servers(self, data: dict[str, Any], servers: dict[str, Any]) -> dict[str, Any]:
        """Return a new config dict with *servers* replacing the current ones."""
        ...

    def get_backup_section(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract the inline _ploston_imported backup section."""
        ...

    def set_backup_section(self, data: dict[str, Any], backup: dict[str, Any]) -> dict[str, Any]:
        """Return a new config dict with the backup section set."""
        ...

    def strip_backup_section(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return a new config dict with the backup section removed."""
        ...

    def decorate_server_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Apply shape-specific decoration to a bridge entry."""
        ...


class McpServersShape:
    """Shape for dict-keyed servers under a configurable top-level key.

    Used by: Claude Desktop, Cursor, Windsurf, Gemini CLI, Cline, Claude Code
    (all use ``mcpServers``), and Codex CLI (uses ``mcp_servers``).

    The ``servers_key`` parameter allows reuse without subclassing.
    """

    BACKUP_KEY = "_ploston_imported"

    def __init__(self, servers_key: str = "mcpServers") -> None:
        self.servers_key = servers_key

    def get_servers(self, data: dict[str, Any]) -> dict[str, Any]:
        return dict(data.get(self.servers_key, {}))

    def set_servers(self, data: dict[str, Any], servers: dict[str, Any]) -> dict[str, Any]:
        out = dict(data)
        out[self.servers_key] = servers
        return out

    def get_backup_section(self, data: dict[str, Any]) -> dict[str, Any]:
        return dict(data.get(self.BACKUP_KEY, {}))

    def set_backup_section(self, data: dict[str, Any], backup: dict[str, Any]) -> dict[str, Any]:
        out = dict(data)
        out[self.BACKUP_KEY] = backup
        return out

    def strip_backup_section(self, data: dict[str, Any]) -> dict[str, Any]:
        out = dict(data)
        out.pop(self.BACKUP_KEY, None)
        return out

    def decorate_server_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """No-op — mcpServers shape entries need no extra keys."""
        return entry


class MicrosoftServersShape:
    """Shape for Microsoft {"servers": {...}, "inputs": [...]} JSON.

    Used by: VS Code Copilot, Visual Studio 2022/2026.
    The ``inputs`` array is preserved verbatim on round-trip.
    """

    SERVERS_KEY = "servers"
    BACKUP_KEY = "_ploston_imported"

    def get_servers(self, data: dict[str, Any]) -> dict[str, Any]:
        return dict(data.get(self.SERVERS_KEY, {}))

    def set_servers(self, data: dict[str, Any], servers: dict[str, Any]) -> dict[str, Any]:
        out = dict(data)
        out[self.SERVERS_KEY] = servers
        return out

    def get_backup_section(self, data: dict[str, Any]) -> dict[str, Any]:
        return dict(data.get(self.BACKUP_KEY, {}))

    def set_backup_section(self, data: dict[str, Any], backup: dict[str, Any]) -> dict[str, Any]:
        out = dict(data)
        out[self.BACKUP_KEY] = backup
        return out

    def strip_backup_section(self, data: dict[str, Any]) -> dict[str, Any]:
        out = dict(data)
        out.pop(self.BACKUP_KEY, None)
        return out

    def decorate_server_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Microsoft shape requires ``"type": "stdio"`` in every server entry."""
        decorated = dict(entry)
        decorated.setdefault("type", "stdio")
        return decorated


class ContextServersShape:
    """Shape for Zed's ``context_servers`` JSON key (S-317).

    Zed settings.json has many sibling keys (theme, telemetry, languages, etc.)
    that must be preserved verbatim on round-trip.
    """

    SERVERS_KEY = "context_servers"
    BACKUP_KEY = "_ploston_imported"

    def get_servers(self, data: dict[str, Any]) -> dict[str, Any]:
        return dict(data.get(self.SERVERS_KEY, {}))

    def set_servers(self, data: dict[str, Any], servers: dict[str, Any]) -> dict[str, Any]:
        out = dict(data)
        out[self.SERVERS_KEY] = servers
        return out

    def get_backup_section(self, data: dict[str, Any]) -> dict[str, Any]:
        return dict(data.get(self.BACKUP_KEY, {}))

    def set_backup_section(self, data: dict[str, Any], backup: dict[str, Any]) -> dict[str, Any]:
        out = dict(data)
        out[self.BACKUP_KEY] = backup
        return out

    def strip_backup_section(self, data: dict[str, Any]) -> dict[str, Any]:
        out = dict(data)
        out.pop(self.BACKUP_KEY, None)
        return out

    def decorate_server_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """No-op — context_servers shape entries need no extra keys."""
        return entry
