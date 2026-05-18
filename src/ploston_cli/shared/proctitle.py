"""Process title helper — makes ploston processes identifiable in ps / Activity Monitor.

Uses ``setproctitle`` (C extension, works on macOS + Linux) to replace the
generic ``python3.12 …/ploston bridge …`` argv with a short, descriptive
label such as ``ploston: bridge/github`` or ``ploston: runner/macbook-pro``.

The import is guarded so a missing wheel never breaks the CLI.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def set_process_title(role: str, detail: str | None = None) -> None:
    """Set the OS process title to ``ploston: <role>[/<detail>]``.

    Args:
        role: Process role — ``bridge``, ``runner``, or ``inspector``.
        detail: Optional qualifier (e.g. bridge name, runner name).

    Examples::

        set_process_title("bridge", "github/claude-desktop")
        # → "ploston: bridge/github/claude-desktop"

        set_process_title("runner", "macbook-pro-local")
        # → "ploston: runner/macbook-pro-local"

        set_process_title("inspector")
        # → "ploston: inspector"
    """
    title = f"ploston: {role}"
    if detail:
        title = f"{title}/{detail}"

    try:
        import setproctitle

        setproctitle.setproctitle(title)
        logger.debug("Process title set to %r", title)
    except ImportError:
        logger.debug("setproctitle not installed — process title unchanged")
    except Exception as exc:  # pragma: no cover
        logger.debug("Failed to set process title: %s", exc)
