"""Unit tests for ploston_cli.shared.paths module."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest


@pytest.mark.cli_unit
class TestPaths:
    """Tests for path constants and functions."""

    def test_ploston_dir_is_in_home(self):
        """Test PLOSTON_DIR is in user's home directory."""
        from ploston_cli.shared.paths import PLOSTON_DIR

        assert PLOSTON_DIR == Path.home() / ".ploston"

    def test_pid_file_location(self):
        """Test PID_FILE is in PLOSTON_DIR."""
        from ploston_cli.shared.paths import PID_FILE, PLOSTON_DIR

        assert PID_FILE == PLOSTON_DIR / "runner.pid"

    def test_log_dir_location(self):
        """Test LOG_DIR is same as PLOSTON_DIR."""
        from ploston_cli.shared.paths import LOG_DIR, PLOSTON_DIR

        assert LOG_DIR == PLOSTON_DIR

    def test_tokens_dir_location(self):
        """Test TOKENS_DIR is in PLOSTON_DIR."""
        from ploston_cli.shared.paths import PLOSTON_DIR, TOKENS_DIR

        assert TOKENS_DIR == PLOSTON_DIR / "tokens"

    def test_ca_dir_location(self):
        """Test CA_DIR is in PLOSTON_DIR."""
        from ploston_cli.shared.paths import CA_DIR, PLOSTON_DIR

        assert CA_DIR == PLOSTON_DIR / "ca"


@pytest.mark.cli_unit
class TestEnsureDirs:
    """Tests for ensure_dirs function."""

    def test_ensure_dirs_creates_directories(self):
        """Test ensure_dirs creates all required directories."""
        with TemporaryDirectory() as tmpdir:
            # Patch the paths to use temp directory
            test_ploston_dir = Path(tmpdir) / ".ploston"
            test_tokens_dir = test_ploston_dir / "tokens"
            test_ca_dir = test_ploston_dir / "ca"

            with (
                patch("ploston_cli.shared.paths.PLOSTON_DIR", test_ploston_dir),
                patch("ploston_cli.shared.paths.TOKENS_DIR", test_tokens_dir),
                patch("ploston_cli.shared.paths.CA_DIR", test_ca_dir),
            ):
                from ploston_cli.shared.paths import ensure_dirs

                # Directories should not exist yet
                assert not test_ploston_dir.exists()
                assert not test_tokens_dir.exists()
                assert not test_ca_dir.exists()

                ensure_dirs()

                # Now they should exist
                assert test_ploston_dir.exists()
                assert test_tokens_dir.exists()
                assert test_ca_dir.exists()

    def test_ensure_dirs_sets_secure_permissions(self):
        """Test ensure_dirs sets 0o700 permissions."""
        with TemporaryDirectory() as tmpdir:
            test_ploston_dir = Path(tmpdir) / ".ploston"
            test_tokens_dir = test_ploston_dir / "tokens"
            test_ca_dir = test_ploston_dir / "ca"

            with (
                patch("ploston_cli.shared.paths.PLOSTON_DIR", test_ploston_dir),
                patch("ploston_cli.shared.paths.TOKENS_DIR", test_tokens_dir),
                patch("ploston_cli.shared.paths.CA_DIR", test_ca_dir),
            ):
                from ploston_cli.shared.paths import ensure_dirs

                ensure_dirs()

                # Check permissions (0o700 = owner read/write/execute only)
                assert (test_ploston_dir.stat().st_mode & 0o777) == 0o700
                assert (test_tokens_dir.stat().st_mode & 0o777) == 0o700
                assert (test_ca_dir.stat().st_mode & 0o777) == 0o700

    def test_ensure_dirs_idempotent(self):
        """Test ensure_dirs can be called multiple times."""
        with TemporaryDirectory() as tmpdir:
            test_ploston_dir = Path(tmpdir) / ".ploston"
            test_tokens_dir = test_ploston_dir / "tokens"
            test_ca_dir = test_ploston_dir / "ca"

            with (
                patch("ploston_cli.shared.paths.PLOSTON_DIR", test_ploston_dir),
                patch("ploston_cli.shared.paths.TOKENS_DIR", test_tokens_dir),
                patch("ploston_cli.shared.paths.CA_DIR", test_ca_dir),
            ):
                from ploston_cli.shared.paths import ensure_dirs

                # Call multiple times - should not raise
                ensure_dirs()
                ensure_dirs()
                ensure_dirs()

                assert test_ploston_dir.exists()


@pytest.mark.cli_unit
class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_log_file(self):
        """Test get_log_file returns correct path."""
        from ploston_cli.shared.paths import LOG_DIR, get_log_file

        assert get_log_file() == LOG_DIR / "runner.log"
        assert get_log_file("custom") == LOG_DIR / "custom.log"

    def test_get_token_file(self):
        """Test get_token_file returns correct path."""
        from ploston_cli.shared.paths import TOKENS_DIR, get_token_file

        assert get_token_file("bridge") == TOKENS_DIR / "bridge.token"
        assert get_token_file("runner") == TOKENS_DIR / "runner.token"
        assert get_token_file("cli") == TOKENS_DIR / "cli.token"
