"""Phase-3 robustness tests for the atomic-write helper.

Config / secret / infra files are written via a temp-file + ``os.replace``
so a crash mid-write never leaves a truncated or empty file in place.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from ploston_cli.shared.atomic import atomic_write_text


def test_writes_correct_content(tmp_path):
    target = tmp_path / "out.txt"
    atomic_write_text(target, "hello world")
    assert target.read_text() == "hello world"


def test_uses_os_replace(tmp_path):
    target = tmp_path / "out.txt"
    real_replace = os.replace
    with patch("ploston_cli.shared.atomic.os.replace", side_effect=real_replace) as m:
        atomic_write_text(target, "data")
    assert m.called, "atomic_write_text must use os.replace for atomicity"
    # The replace source must be a *different* temp path in the same dir.
    src, dst = m.call_args[0][0], m.call_args[0][1]
    assert str(dst) == str(target)
    assert str(src) != str(target)
    assert os.path.dirname(str(src)) == os.path.dirname(str(target))


def test_partial_write_does_not_clobber_existing(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("original-content")

    # Simulate a crash during the temp-file write (before os.replace).
    with patch("ploston_cli.shared.atomic.os.replace", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            atomic_write_text(target, "new-content-that-fails")

    # Original file is untouched; no temp turds left behind.
    assert target.read_text() == "original-content"
    leftovers = [p for p in tmp_path.iterdir() if p != target]
    assert leftovers == [], f"temp files not cleaned up: {leftovers}"


def test_respects_mode(tmp_path):
    import stat
    import sys

    if sys.platform.startswith("win"):
        pytest.skip("POSIX modes only")
    target = tmp_path / "secret.txt"
    atomic_write_text(target, "s3cr3t", mode=0o600)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
