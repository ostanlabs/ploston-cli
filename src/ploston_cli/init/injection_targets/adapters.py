"""Config shape adapters (T-990, DEC-198; refactored in S-315, DEC-204).

McpServersAdapter  — canonical {"mcpServers": {...}} JSON.
MicrosoftServersAdapter — {"servers": {...}, "inputs": [...]} JSON.

Post-S-315: Both are thin CompositeAdapter subclasses composed from
JsonFormat + the appropriate ConfigShape.  The public API surface
(class names, attribute names, method signatures) is unchanged.
"""

from __future__ import annotations

from .composite import CompositeAdapter
from .formats import JsonFormat
from .shapes import McpServersShape, MicrosoftServersShape


class McpServersAdapter(CompositeAdapter):
    """Adapter for the standard mcpServers JSON shape.

    Used by: Claude Desktop, Cursor, Windsurf, Gemini CLI, Cline, Claude Code.

    Public API — importable and stable per DEC-206.
    """

    SERVERS_KEY = "mcpServers"
    BACKUP_KEY = "_ploston_imported"

    def __init__(self) -> None:
        super().__init__(format=JsonFormat(), shape=McpServersShape())


class MicrosoftServersAdapter(CompositeAdapter):
    """Adapter for the Microsoft {"servers": {...}, "inputs": [...]} JSON shape.

    Used by: VS Code Copilot, Visual Studio 2022/2026.
    The ``inputs`` array is preserved verbatim on round-trip.

    Public API — importable and stable per DEC-206.
    """

    SERVERS_KEY = "servers"
    BACKUP_KEY = "_ploston_imported"

    def __init__(self) -> None:
        super().__init__(format=JsonFormat(), shape=MicrosoftServersShape())
