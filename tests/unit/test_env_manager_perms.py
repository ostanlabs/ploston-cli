"""Phase-3 robustness tests for env_manager secret-file permissions.

The ``~/.ploston/.env`` file holds secrets (runner token + imported MCP
secrets) and must never be world-readable. After ``write_env_file`` the file
mode must be ``0o600`` and its parent directory ``0o700``.
"""

from __future__ import annotations

import stat
import sys

import pytest

from ploston_cli.init.env_manager import write_env_file

pytestmark = pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX file modes only")


def test_write_env_file_is_owner_only(tmp_path):
    env_file = tmp_path / ".ploston" / ".env"

    result = write_env_file(
        runner_token="ploston_runner_secret",
        env_vars={"API_KEY": "supersecret"},
        env_file_path=env_file,
    )

    mode = stat.S_IMODE(result.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_write_env_file_parent_dir_is_owner_only(tmp_path):
    env_file = tmp_path / ".ploston" / ".env"

    write_env_file(
        runner_token="ploston_runner_secret",
        env_vars=None,
        env_file_path=env_file,
    )

    dir_mode = stat.S_IMODE(env_file.parent.stat().st_mode)
    assert dir_mode == 0o700, f"expected 0o700, got {oct(dir_mode)}"
