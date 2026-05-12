"""CompositeAdapter — compose a ConfigFormat + ConfigShape into a ConfigAdapter (S-315, DEC-204).

``isinstance(CompositeAdapter(...), ConfigAdapter)`` is True via Protocol runtime check.
Existing code that accepts a ``ConfigAdapter`` accepts a ``CompositeAdapter`` interchangeably.

Internal API — not part of the public stability contract (DEC-206).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .formats import ConfigFormat
from .shapes import ConfigShape


class CompositeAdapter:
    """Delegates each ConfigAdapter Protocol method to the appropriate layer.

    Format → read/write (I/O).
    Shape  → get_servers / set_servers / backup / decorate (structure).
    """

    def __init__(self, format: ConfigFormat, shape: ConfigShape) -> None:
        self.format = format
        self.shape = shape

    # --- Format-delegated ---

    def read(self, path: Path) -> dict[str, Any]:
        return self.format.read(path)

    def write(self, path: Path, data: dict[str, Any]) -> None:
        return self.format.write(path, data)

    # --- Shape-delegated ---

    def get_servers(self, data: dict[str, Any]) -> dict[str, Any]:
        return self.shape.get_servers(data)

    def set_servers(self, data: dict[str, Any], servers: dict[str, Any]) -> dict[str, Any]:
        return self.shape.set_servers(data, servers)

    def get_backup_section(self, data: dict[str, Any]) -> dict[str, Any]:
        return self.shape.get_backup_section(data)

    def set_backup_section(self, data: dict[str, Any], backup: dict[str, Any]) -> dict[str, Any]:
        return self.shape.set_backup_section(data, backup)

    def strip_backup_section(self, data: dict[str, Any]) -> dict[str, Any]:
        return self.shape.strip_backup_section(data)

    def decorate_server_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        return self.shape.decorate_server_entry(entry)
