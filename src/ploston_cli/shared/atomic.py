"""Atomic file-write helpers.

Config, secret, and infra files are written to a temporary file in the *same*
directory and then ``os.replace``-d into place. ``os.replace`` is atomic on
POSIX and Windows for paths on the same filesystem, so a crash mid-write can
never leave a truncated or empty file where a valid one used to be.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = ["atomic_write_text", "atomic_write_bytes"]


def atomic_write_bytes(path: Path | str, data: bytes, *, mode: int | None = None) -> Path:
    """Atomically write *data* to *path*.

    Writes to a temp file in the same directory, fsyncs it, then atomically
    renames it over *path*. The temp file is always cleaned up on failure.

    Args:
        path: Destination path.
        data: Bytes to write.
        mode: Optional POSIX file mode (e.g. ``0o600``) applied to the temp
              file before the rename so the final file never briefly exists
              with looser permissions.

    Returns:
        The destination path.
    """
    dest = Path(path)
    directory = dest.parent
    directory.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=str(directory))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp_name, mode)
        os.replace(tmp_name, dest)
    except BaseException:
        # Clean up the temp file on any failure (including the replace step).
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return dest


def atomic_write_text(
    path: Path | str,
    text: str,
    *,
    mode: int | None = None,
    encoding: str = "utf-8",
) -> Path:
    """Atomically write *text* to *path*. See :func:`atomic_write_bytes`."""
    return atomic_write_bytes(path, text.encode(encoding), mode=mode)
