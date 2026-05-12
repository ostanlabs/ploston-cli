"""Layer-2 backup: pre-modification file copy (T-1006).

Before Ploston modifies a config for the first time, the injector copies the
untouched file to ``<config_path>.ploston-backup-<ISO-timestamp>`` next to it.

Rules (from spec §3.4):
- One backup per target per "first touch." Subsequent injections do NOT create
  new backup copies — they update ``_ploston_imported`` (Layer 1) only.
- The backup file is excluded from detection by ConfigDetector.
- Skippable via ``--no-backup-file`` flag.
- Permissions of the backup match the original file.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_BACKUP_PATTERN = re.compile(r"\.ploston-backup-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")


def _has_existing_backup(config_path: Path) -> bool:
    """Return True if a Layer-2 backup already exists for *config_path*."""
    parent = config_path.parent
    stem = config_path.name
    if not parent.exists():
        return False
    for entry in parent.iterdir():
        if entry.name.startswith(stem) and _BACKUP_PATTERN.search(entry.name):
            return True
    return False


def make_backup(config_path: Path) -> Path | None:
    """Create a Layer-2 backup of *config_path* if none exists yet.

    Returns the backup path if a new backup was created, or None if a backup
    already exists (idempotency) or the source file doesn't exist.
    """
    if not config_path.exists():
        return None

    if _has_existing_backup(config_path):
        logger.debug("Layer-2 backup already exists for %s — skipping.", config_path)
        return None

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    backup_path = config_path.parent / f"{config_path.name}.ploston-backup-{ts}"

    shutil.copy2(config_path, backup_path)
    # Explicitly match permissions (belt-and-suspenders on top of copy2)
    os.chmod(backup_path, config_path.stat().st_mode)
    logger.info("Layer-2 backup created: %s", backup_path)
    return backup_path


def find_latest_backup(config_path: Path) -> Path | None:
    """Return the most recent Layer-2 backup for *config_path*, or None."""
    parent = config_path.parent
    stem = config_path.name
    if not parent.exists():
        return None

    backups: list[Path] = []
    for entry in parent.iterdir():
        if entry.name.startswith(stem) and _BACKUP_PATTERN.search(entry.name):
            backups.append(entry)

    if not backups:
        return None

    # Sort by filename (ISO timestamp in name ensures lexicographic = chronological)
    backups.sort(key=lambda p: p.name)
    return backups[-1]


def restore_from_backup(config_path: Path) -> bool:
    """Restore *config_path* from its most recent Layer-2 backup.

    Returns True if restored, False if no backup found.
    """
    backup = find_latest_backup(config_path)
    if backup is None:
        return False

    shutil.copy2(backup, config_path)
    os.chmod(config_path, backup.stat().st_mode)
    logger.info("Restored %s from Layer-2 backup %s", config_path, backup)
    return True


def is_backup_file(path: Path) -> bool:
    """Return True if *path* looks like a Layer-2 backup file."""
    return bool(_BACKUP_PATTERN.search(path.name))
