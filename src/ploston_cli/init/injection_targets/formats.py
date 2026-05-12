"""Config file format abstractions (S-315, DEC-204).

ConfigFormat owns I/O: how to read/write a config file.
Format does not know or care what's inside the structure.

Internal API — not part of the public stability contract (DEC-206).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ConfigFormat(Protocol):
    """Protocol for file format read/write."""

    def read(self, path: Path) -> dict[str, Any]:
        """Read and deserialize the file at *path*."""
        ...

    def write(self, path: Path, data: dict[str, Any]) -> None:
        """Serialize and write *data* to *path*."""
        ...


class JsonFormat:
    """JSON file format with pretty-printing and trailing newline."""

    def read(self, path: Path) -> dict[str, Any]:
        import json

        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, path: Path, data: dict[str, Any]) -> None:
        import json

        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


class TomlFormat:
    """TOML file format using tomlkit for comment-preserving round-trip (S-316, DEC-205).

    ``read()`` returns a ``tomlkit.TOMLDocument`` which behaves like a dict
    for shape-layer operations.  ``write()`` serializes through ``tomlkit.dumps``
    which preserves comments on unmodified sections (best-effort guarantee).
    """

    def read(self, path: Path) -> dict[str, Any]:
        import tomlkit

        return tomlkit.loads(path.read_text(encoding="utf-8"))

    def write(self, path: Path, data: dict[str, Any]) -> None:
        import tomlkit

        path.write_text(
            tomlkit.dumps(data),
            encoding="utf-8",
        )
