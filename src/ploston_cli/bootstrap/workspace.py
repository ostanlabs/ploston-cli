"""Workspace detection for build-from-source support.

Detects whether the current working directory is inside the ploston
meta-repo (agent-execution-layer), which is required for building
Docker images from local source.
"""

from __future__ import annotations

from pathlib import Path


def detect_meta_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from start (default: cwd) looking for the meta-repo root.

    The meta-repo is identified by the presence of both:
    - packages/ploston/ directory
    - ci/images.yaml file

    Args:
        start: Starting directory. Defaults to Path.cwd().

    Returns:
        Path to the meta-repo root, or None if not found.
    """
    cwd = start or Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "packages" / "ploston").is_dir() and (parent / "ci" / "images.yaml").is_file():
            return parent
    return None
