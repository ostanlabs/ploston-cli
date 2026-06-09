"""Layer-2 backup: pre-modification file copy (T-1006, hardened for FB-1).

Before Ploston modifies a config, the injector copies the file to a timestamped
sibling so the pre-modification state is always recoverable.

Rules (FB-1 hardening — supersedes the original single-backup rule):
- A fresh timestamped backup is created on EVERY touch (never clobber a prior
  one), so a rollback target is never frozen at first-touch / stale.
- Backups of an ALREADY-INJECTED config are TAGGED (``-injected-``) and are
  excluded from the canonical restore selection, so rollback can never restore
  a bridged config.
- ``find_latest_backup`` / ``restore_from_backup`` return the most-recent
  KNOWN-GOOD (non-injected) backup.
- Bounded rotation keeps the last N known-good backups but NEVER deletes the
  only known-good backup.
- The backup files are excluded from detection by ConfigDetector.
- Skippable via ``--no-backup-file`` flag.
- Permissions of the backup match the original file.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Timestamp with sub-second precision (microseconds) + optional counter suffix
# so that rapid successive backups in the same second never collide.
_TS = r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:-\d{6})?(?:-\d+)?Z"
# Known-good (clean) backups.
_BACKUP_PATTERN = re.compile(r"\.ploston-backup-" + _TS + r"$")
# Backups taken from an already-injected config — never a canonical restore point.
_INJECTED_BACKUP_PATTERN = re.compile(r"\.ploston-backup-injected-" + _TS + r"$")

# How many known-good backups to retain (rotation bound).
_MAX_KNOWN_GOOD_BACKUPS = 10


def _has_existing_backup(config_path: Path) -> bool:
    """Return True if any Layer-2 backup (clean or injected) exists.

    Retained for backwards compatibility / introspection. The injector no
    longer short-circuits on this — backups now rotate on every touch.
    """
    parent = config_path.parent
    stem = config_path.name
    if not parent.exists():
        return False
    for entry in parent.iterdir():
        if entry.name.startswith(stem) and (
            _INJECTED_BACKUP_PATTERN.search(entry.name) or _BACKUP_PATTERN.search(entry.name)
        ):
            return True
    return False


def _timestamp() -> str:
    """UTC timestamp string with microsecond precision (collision-resistant)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")


def _unique_backup_path(parent: Path, base_name: str) -> Path:
    """Return a non-existing backup path, appending a counter on collision."""
    candidate = parent / base_name
    counter = 0
    # base_name ends in "...-<micro>Z"; insert counter before the trailing Z.
    while candidate.exists():
        counter += 1
        candidate = parent / (base_name[:-1] + f"-{counter}Z")
    return candidate


def _config_is_injected(path: Path) -> bool:
    """Best-effort check whether *path* holds an already-injected config.

    A config is considered injected if it has a top-level ``ploston`` entry in
    ``mcpServers`` (mirrors :func:`injector.is_already_injected` without the
    import cycle). Unreadable / malformed files are treated as NOT injected so
    we still preserve a copy of whatever was there.
    """
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return False
    if not isinstance(config, dict):
        return False
    mcp = config.get("mcpServers", {})
    return isinstance(mcp, dict) and "ploston" in mcp


def make_backup(config_path: Path) -> Path | None:
    """Create a fresh Layer-2 backup of *config_path* on every touch.

    - If the source file does not exist, returns None.
    - If the source is already injected, the backup is TAGGED ``-injected-`` so
      it is excluded from canonical restore selection (FB-1 defect B).
    - Otherwise a fresh known-good timestamped backup is created and the set of
      known-good backups is rotated to the last ``_MAX_KNOWN_GOOD_BACKUPS``
      (never deleting the only known-good backup).

    Returns the new backup path, or None if the source file doesn't exist.
    """
    if not config_path.exists():
        return None

    parent = config_path.parent
    ts = _timestamp()

    if _config_is_injected(config_path):
        # Never canonicalise an injected config as a restore point.
        base = f"{config_path.name}.ploston-backup-injected-{ts}"
        backup_path = _unique_backup_path(parent, base)
        shutil.copy2(config_path, backup_path)
        os.chmod(backup_path, config_path.stat().st_mode)
        logger.warning(
            "Layer-2 backup of an ALREADY-INJECTED config tagged as %s "
            "and excluded from rollback (a known-good backup is the restore "
            "point).",
            backup_path.name,
        )
        return backup_path

    base = f"{config_path.name}.ploston-backup-{ts}"
    backup_path = _unique_backup_path(parent, base)
    shutil.copy2(config_path, backup_path)
    # Explicitly match permissions (belt-and-suspenders on top of copy2)
    os.chmod(backup_path, config_path.stat().st_mode)
    logger.info("Layer-2 backup created: %s", backup_path)

    _rotate_known_good_backups(config_path)
    return backup_path


def _list_known_good_backups(config_path: Path) -> list[Path]:
    """Return clean (non-injected, non-tagged) Layer-2 backups, oldest→newest."""
    parent = config_path.parent
    stem = config_path.name
    if not parent.exists():
        return []
    backups: list[Path] = []
    for entry in parent.iterdir():
        if not entry.name.startswith(stem):
            continue
        # Exclude tagged injected backups explicitly.
        if _INJECTED_BACKUP_PATTERN.search(entry.name):
            continue
        if not _BACKUP_PATTERN.search(entry.name):
            continue
        # Defense-in-depth: even a clean-named backup must not be canonical if
        # its CONTENTS are an injected (bridged) config — restoring it would
        # re-bridge the user's config (FB-1 defect B).
        if _config_is_injected(entry):
            continue
        backups.append(entry)
    # Filename timestamps sort lexicographically == chronologically.
    backups.sort(key=lambda p: p.name)
    return backups


def _rotate_known_good_backups(config_path: Path) -> None:
    """Trim known-good backups to the last ``_MAX_KNOWN_GOOD_BACKUPS``.

    Never deletes the only/most-recent known-good backup.
    """
    backups = _list_known_good_backups(config_path)
    if len(backups) <= _MAX_KNOWN_GOOD_BACKUPS:
        return
    # Delete the oldest, but always keep at least the newest one.
    excess = backups[:-_MAX_KNOWN_GOOD_BACKUPS]
    for old in excess:
        try:
            old.unlink()
            logger.debug("Rotated out old Layer-2 backup: %s", old.name)
        except OSError:
            logger.debug("Could not remove old backup %s", old.name)


def find_latest_backup(config_path: Path) -> Path | None:
    """Return the most recent KNOWN-GOOD Layer-2 backup, or None.

    Injected (``-injected-`` tagged) backups are never returned, so a rollback
    can never restore a bridged config (FB-1 defect B).
    """
    backups = _list_known_good_backups(config_path)
    if not backups:
        return None
    return backups[-1]


def restore_from_backup(config_path: Path) -> bool:
    """Restore *config_path* from its most recent KNOWN-GOOD Layer-2 backup.

    Returns True if restored, False if no known-good backup found.
    """
    backup = find_latest_backup(config_path)
    if backup is None:
        return False

    shutil.copy2(backup, config_path)
    os.chmod(config_path, backup.stat().st_mode)
    logger.info("Restored %s from Layer-2 backup %s", config_path, backup)
    return True


def is_backup_file(path: Path) -> bool:
    """Return True if *path* looks like any Layer-2 backup file (clean or injected)."""
    return bool(_INJECTED_BACKUP_PATTERN.search(path.name) or _BACKUP_PATTERN.search(path.name))
