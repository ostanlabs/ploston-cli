"""Config shape adapters (T-990, DEC-198).

McpServersAdapter  — canonical {"mcpServers": {...}} JSON.
MicrosoftServersAdapter — {"servers": {...}, "inputs": [...]} JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class McpServersAdapter:
    """Adapter for the standard mcpServers JSON shape.

    Used by: Claude Desktop, Cursor, Windsurf, Gemini CLI, Cline, Claude Code.
    """

    SERVERS_KEY = "mcpServers"
    BACKUP_KEY = "_ploston_imported"

    def read(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, path: Path, data: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

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


class MicrosoftServersAdapter:
    """Adapter for the Microsoft {"servers": {...}, "inputs": [...]} JSON shape.

    Used by: VS Code Copilot, Visual Studio 2022/2026.
    The ``inputs`` array is preserved verbatim on round-trip.
    """

    SERVERS_KEY = "servers"
    BACKUP_KEY = "_ploston_imported"

    def read(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, path: Path, data: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

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
