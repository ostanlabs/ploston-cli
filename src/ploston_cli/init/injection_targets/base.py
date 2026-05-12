"""Base classes for the injection target plugin system (T-989, DEC-198).

InjectionTarget owns identity + path resolution for an agent.
ConfigAdapter owns the file shape (where servers live in JSON).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# ConfigAdapter protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ConfigAdapter(Protocol):
    """Protocol for reading/writing servers within a config file shape.

    Implementations handle the specific JSON structure of different agent
    config formats (mcpServers shape, Microsoft servers shape, etc.).
    """

    def read(self, path: Path) -> dict[str, Any]:
        """Read the full config dict from *path*."""
        ...

    def write(self, path: Path, data: dict[str, Any]) -> None:
        """Write the full config dict to *path* (pretty JSON + trailing newline)."""
        ...

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


# ---------------------------------------------------------------------------
# InjectionTarget base class
# ---------------------------------------------------------------------------

Scope = Literal["global", "project"]


class InjectionTarget:
    """Base class for an injection target (one per agent config location).

    Subclass and register in TARGET_REGISTRY to add a new target.
    The base class provides sensible defaults for the 80% case
    (mcpServers shape, global scope).
    """

    source_id: str
    display_name: str
    scope: Scope
    adapter: ConfigAdapter

    # Per-platform path templates.  Keys: "darwin", "linux", "windows".
    # Substitutions: {home} = Path.home(), {cwd} = git root or cwd.
    config_path_template: dict[str, str]

    def detect(self, home: Path, cwd: Path) -> Path | None:
        """Resolve the config path on this platform.

        Returns the expanded Path if the template exists for this OS,
        or None if the target doesn't apply to this platform.
        """
        platform = _current_platform()
        template = self.config_path_template.get(platform)
        if template is None:
            return None
        return Path(template.format(home=str(home), cwd=str(cwd)))

    def make_ploston_entry(
        self,
        *,
        cp_url: str,
        expose: str | None = None,
        runner_name: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build a single entry for injection into this target's config.

        The default implementation returns the standard mcpServers shape.
        Override for targets that need extra keys (e.g. Microsoft "type": "stdio").
        """
        from ..injector import _bridge_entry

        return _bridge_entry(
            cp_url=cp_url,
            expose=expose,
            runner_name=runner_name,
            tags=tags,
        )


def _current_platform() -> str:
    """Map sys.platform to our platform keys."""
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "windows"
    return "linux"
