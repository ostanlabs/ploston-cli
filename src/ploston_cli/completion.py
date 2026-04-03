"""Dynamic shell completions for Ploston CLI.

Provides ``PlostCompletionSource`` which reads from a local cache file
(``~/.ploston/.completions_cache.json``) to provide tab-completion values
for workflow names, runner names, server names, and tag values.

The cache is updated opportunistically by any successful CP-connected
command (fire-and-forget ``asyncio.create_task``).

See: DEC169-175_ROUTING_TAGS_CLI_SPEC.md §5 (T-767)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from click.shell_completion import CompletionItem

logger = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".ploston"
_CACHE_FILE = _CACHE_DIR / ".completions_cache.json"


class PlostCompletionSource:
    """Reads the completions cache and returns matching items.

    All public methods are safe — file read errors return empty lists
    (never crash tab completion).
    """

    def __init__(self, cache_path: Path | None = None) -> None:
        self._cache_path = cache_path or _CACHE_FILE

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self._cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def workflows(self) -> list[str]:
        return self._load().get("workflows", [])

    def runners(self) -> list[str]:
        return self._load().get("runners", [])

    def servers(self) -> list[str]:
        return self._load().get("servers", [])

    def tags(self) -> list[str]:
        return self._load().get("tags", [])


# ---------------------------------------------------------------------------
# Cache writer (called from commands after a successful CP call)
# ---------------------------------------------------------------------------


def write_completions_cache(
    *,
    workflows: list[str] | None = None,
    runners: list[str] | None = None,
    servers: list[str] | None = None,
    tags: list[str] | None = None,
    cache_path: Path | None = None,
) -> None:
    """Merge new data into the completions cache file.

    Only non-``None`` keys are overwritten; others are preserved from the
    existing cache.  ``updated_at`` is always refreshed.
    """
    path = cache_path or _CACHE_FILE
    existing: dict[str, Any] = {}
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass

    if workflows is not None:
        existing["workflows"] = sorted(set(workflows))
    if runners is not None:
        existing["runners"] = sorted(set(runners))
    if servers is not None:
        existing["servers"] = sorted(set(servers))
    if tags is not None:
        existing["tags"] = sorted(set(tags))
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    except Exception:
        logger.debug("Failed to write completions cache", exc_info=True)


# ---------------------------------------------------------------------------
# Click completion callbacks
# ---------------------------------------------------------------------------

_source = PlostCompletionSource()


def complete_workflow_names(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    return [CompletionItem(n) for n in _source.workflows() if n.startswith(incomplete)]


def complete_runner_names(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    return [CompletionItem(n) for n in _source.runners() if n.startswith(incomplete)]


def complete_server_names(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    return [CompletionItem(n) for n in _source.servers() if n.startswith(incomplete)]


def complete_tag_values(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    return [CompletionItem(n) for n in _source.tags() if n.startswith(incomplete)]
