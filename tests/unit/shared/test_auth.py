"""Unit tests for ploston_cli.shared.auth module."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from ploston_cli.shared.auth import (
    auth_headers,
    delete_token,
    get_token,
    get_token_file_path,
    save_token,
)


@pytest.mark.cli_unit
class TestGetToken:
    """Tests for get_token function."""

    def test_token_from_cli_arg(self):
        """Test token from CLI argument takes priority."""
        with TemporaryDirectory() as tmpdir:
            tokens_dir = Path(tmpdir) / "tokens"
            tokens_dir.mkdir()

            with patch("ploston_cli.shared.auth.TOKENS_DIR", tokens_dir):
                # Even with env var and file, CLI arg wins
                os.environ["TEST_TOKEN"] = "env-token"
                (tokens_dir / "test.token").write_text("file-token")

                result = get_token("test", token_arg="cli-token", env_var="TEST_TOKEN")

                assert result == "cli-token"

                del os.environ["TEST_TOKEN"]

    def test_token_from_env_var(self):
        """Test token from environment variable."""
        with TemporaryDirectory() as tmpdir:
            tokens_dir = Path(tmpdir) / "tokens"
            tokens_dir.mkdir()

            with patch("ploston_cli.shared.auth.TOKENS_DIR", tokens_dir):
                os.environ["TEST_TOKEN"] = "env-token"

                result = get_token("test", env_var="TEST_TOKEN")

                assert result == "env-token"

                del os.environ["TEST_TOKEN"]

    def test_token_from_file(self):
        """Test token from stored file."""
        with TemporaryDirectory() as tmpdir:
            tokens_dir = Path(tmpdir) / "tokens"
            tokens_dir.mkdir()
            (tokens_dir / "test.token").write_text("file-token\n")

            with patch("ploston_cli.shared.auth.TOKENS_DIR", tokens_dir):
                result = get_token("test")

                assert result == "file-token"

    def test_token_not_found(self):
        """Test returns None when no token available."""
        with TemporaryDirectory() as tmpdir:
            tokens_dir = Path(tmpdir) / "tokens"
            tokens_dir.mkdir()

            with patch("ploston_cli.shared.auth.TOKENS_DIR", tokens_dir):
                result = get_token("nonexistent")

                assert result is None


@pytest.mark.cli_unit
class TestAuthHeaders:
    """Tests for auth_headers function."""

    def test_auth_headers_with_token(self):
        """Test auth headers with token."""
        headers = auth_headers("my-token")

        assert headers == {"Authorization": "Bearer my-token"}

    def test_auth_headers_without_token(self):
        """Test auth headers without token."""
        headers = auth_headers(None)

        assert headers == {}


@pytest.mark.cli_unit
class TestSaveToken:
    """Tests for save_token function."""

    def test_save_token(self):
        """Test saving a token."""
        with TemporaryDirectory() as tmpdir:
            tokens_dir = Path(tmpdir) / "tokens"

            with patch("ploston_cli.shared.auth.TOKENS_DIR", tokens_dir):
                save_token("test", "my-secret-token")

                token_file = tokens_dir / "test.token"
                assert token_file.exists()
                assert token_file.read_text() == "my-secret-token"

    def test_save_token_secure_permissions(self):
        """Test saved token has secure permissions."""
        with TemporaryDirectory() as tmpdir:
            tokens_dir = Path(tmpdir) / "tokens"

            with patch("ploston_cli.shared.auth.TOKENS_DIR", tokens_dir):
                save_token("test", "my-secret-token")

                token_file = tokens_dir / "test.token"
                mode = token_file.stat().st_mode & 0o777
                assert mode == 0o600


@pytest.mark.cli_unit
class TestDeleteToken:
    """Tests for delete_token function."""

    def test_delete_existing_token(self):
        """Test deleting an existing token."""
        with TemporaryDirectory() as tmpdir:
            tokens_dir = Path(tmpdir) / "tokens"
            tokens_dir.mkdir()
            (tokens_dir / "test.token").write_text("token")

            with patch("ploston_cli.shared.auth.TOKENS_DIR", tokens_dir):
                result = delete_token("test")

                assert result is True
                assert not (tokens_dir / "test.token").exists()

    def test_delete_nonexistent_token(self):
        """Test deleting a nonexistent token."""
        with TemporaryDirectory() as tmpdir:
            tokens_dir = Path(tmpdir) / "tokens"
            tokens_dir.mkdir()

            with patch("ploston_cli.shared.auth.TOKENS_DIR", tokens_dir):
                result = delete_token("nonexistent")

                assert result is False


@pytest.mark.cli_unit
class TestGetTokenFilePath:
    """Tests for get_token_file_path function."""

    def test_get_token_file_path(self):
        """Test getting token file path."""
        with TemporaryDirectory() as tmpdir:
            tokens_dir = Path(tmpdir) / "tokens"

            with patch("ploston_cli.shared.auth.TOKENS_DIR", tokens_dir):
                path = get_token_file_path("bridge")

                assert path == tokens_dir / "bridge.token"
