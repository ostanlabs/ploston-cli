"""Interactive target selector for injection (T-1002, DEC-199 Option B).

Presents a questionary checkbox picker where:
- Targets that contributed at least one selected server are pre-checked.
- Targets with an existing config but no contributing servers are unchecked but selectable.
- Targets without a config file on disk are not shown at all.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from pathlib import Path
from typing import TYPE_CHECKING

import questionary

from .injector import SOURCE_LABELS

if TYPE_CHECKING:
    from .detector import DetectedConfig


def _shorten_home(path: Path) -> str:
    """Replace the home directory prefix with ~ for display."""
    home = str(Path.home())
    s = str(path)
    if s.startswith(home):
        return "~" + s[len(home) :]
    return s


def select_targets(
    detected_configs: list[DetectedConfig],
    selected_server_names: list[str],
    non_interactive: bool = False,
    inject_targets: list[str] | None = None,
) -> list[str]:
    """Return the list of source_ids the user wants to inject into.

    Decision logic (DEC-199 Option B):
    - ``inject_targets`` is set (--inject-target flag): return those verbatim.
    - ``non_interactive``: return only targets that contributed a selected server
      (the "contributors" set — same as today's silent-inject behaviour).
    - Interactive with 0 or 1 viable targets: return the viable set without prompting.
    - Interactive with ≥2 viable targets: show a checkbox picker.

    Args:
        detected_configs: All DetectedConfig objects from ConfigDetector.detect_all().
        selected_server_names: Server names the user selected in step 3.
        non_interactive: True when --non-interactive was passed.
        inject_targets: Explicit --inject-target values (bypass picker).

    Returns:
        List of source_id strings to inject into.
    """
    # Fast path: explicit flag
    if inject_targets:
        return list(inject_targets)

    # Build contributor set: targets whose config file contributed a selected server
    contributors: set[str] = set()
    for dc in detected_configs:
        if dc.found and dc.path and dc.servers:
            if any(s in selected_server_names for s in dc.servers):
                contributors.add(dc.source)

    # Build viable set: targets with an existing config file on disk
    viable: list[str] = []
    for dc in detected_configs:
        if dc.found and dc.path:
            viable.append(dc.source)

    # Non-interactive: contributors only
    if non_interactive:
        return [v for v in viable if v in contributors]

    # 0 or 1 viable → no picker needed
    if len(viable) <= 1:
        return viable

    # Build choices for questionary checkbox
    choices: list[questionary.Choice] = []
    for source_id in viable:
        label = SOURCE_LABELS.get(source_id, source_id)
        # Find the detected path for display
        dc = next((d for d in detected_configs if d.source == source_id), None)
        path_display = _shorten_home(dc.path) if dc and dc.path else ""
        title = f"{label:<24} {path_display}"
        choices.append(
            questionary.Choice(
                title=title,
                value=source_id,
                checked=(source_id in contributors),
            )
        )

    prompt = questionary.checkbox(
        "Select agents to route through Ploston (↑↓ navigate, Space toggle, Enter confirm):",
        choices=choices,
    )

    # questionary.ask() internally calls asyncio.run() which fails when
    # already inside an event loop (e.g. called from async _complete_import_flow).
    # In that case, run the blocking prompt in a separate thread with its own
    # event loop so prompt_toolkit's internal asyncio.run() succeeds.
    try:
        asyncio.get_running_loop()
        in_async = True
    except RuntimeError:
        in_async = False

    if in_async:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(prompt.unsafe_ask)
            selected = future.result()
    else:
        selected = prompt.ask()

    # User pressed Ctrl-C → None
    if selected is None:
        return []

    return selected
