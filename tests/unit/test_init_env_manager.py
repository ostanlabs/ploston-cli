"""Unit tests for ploston init env_manager module."""

from __future__ import annotations

import pytest

from ploston_cli.init.env_manager import (
    EnvFileManager,
    generate_runner_token,
    load_env_file,
    write_env_file,
)


class TestGenerateRunnerToken:
    """Tests for generate_runner_token function."""

    def test_token_format(self):
        """Test that generated token has correct format."""
        token = generate_runner_token()

        assert token.startswith("plr_")
        # Token uses token_urlsafe(32) which produces ~43 chars
        # plr_ prefix + 43 chars = ~47 chars
        assert len(token) > 40

    def test_token_uniqueness(self):
        """Test that tokens are unique."""
        tokens = [generate_runner_token() for _ in range(100)]
        assert len(set(tokens)) == 100


class TestEnvFileManager:
    """Tests for EnvFileManager class."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create an EnvFileManager with temp env file path."""
        env_file = tmp_path / ".ploston" / ".env"
        return EnvFileManager(env_file)

    def test_write_creates_directory(self, tmp_path):
        """Test that write creates the directory if it doesn't exist."""
        env_file = tmp_path / ".ploston" / ".env"
        manager = EnvFileManager(env_file)

        manager.write(runner_token="plr_test123", env_vars={"API_KEY": "secret"})

        assert env_file.parent.exists()
        assert env_file.exists()

    def test_write_content(self, tmp_path):
        """Test that write creates correct content."""
        env_file = tmp_path / ".ploston" / ".env"
        manager = EnvFileManager(env_file)

        manager.write(
            runner_token="plr_test123",
            env_vars={"API_KEY": "secret", "OTHER_VAR": "value"},
        )

        content = env_file.read_text()

        assert "PLOSTON_RUNNER_TOKEN=plr_test123" in content
        assert "API_KEY=secret" in content
        assert "OTHER_VAR=value" in content

    def test_write_special_chars(self, tmp_path):
        """Test that special characters are written correctly."""
        env_file = tmp_path / ".ploston" / ".env"
        manager = EnvFileManager(env_file)

        manager.write(
            runner_token="plr_test",
            env_vars={"PASSWORD": 'pass"word$with`special'},
        )

        content = env_file.read_text()

        # The value should be written as-is (no escaping in this implementation)
        assert 'PASSWORD=pass"word$with`special' in content

    def test_load_existing(self, tmp_path):
        """Test loading existing env file."""
        env_file = tmp_path / ".ploston" / ".env"
        env_file.parent.mkdir(parents=True)
        env_file.write_text("EXISTING_VAR=existing_value\nOTHER=other\n")

        manager = EnvFileManager(env_file)
        result = manager.load()

        assert result == {"EXISTING_VAR": "existing_value", "OTHER": "other"}

    def test_load_nonexistent(self, tmp_path):
        """Test loading when env file doesn't exist."""
        env_file = tmp_path / ".ploston" / ".env"
        manager = EnvFileManager(env_file)

        result = manager.load()
        assert result == {}

    def test_update_preserves_existing(self, tmp_path):
        """Test that update preserves existing variables."""
        env_file = tmp_path / ".ploston" / ".env"
        env_file.parent.mkdir(parents=True)
        env_file.write_text("PLOSTON_RUNNER_TOKEN=plr_existing\nEXISTING=keep_me\n")

        manager = EnvFileManager(env_file)
        manager.update({"NEW_VAR": "new_value"})

        content = env_file.read_text()
        assert "EXISTING=keep_me" in content
        assert "NEW_VAR=new_value" in content


class TestWriteEnvFile:
    """Tests for write_env_file convenience function."""

    def test_write_env_file(self, tmp_path):
        """Test the convenience function."""
        env_file = tmp_path / ".ploston" / ".env"

        result = write_env_file(
            runner_token="plr_test",
            env_vars={"KEY": "value"},
            env_file_path=env_file,
        )

        assert result == env_file
        assert result.exists()
        content = result.read_text()
        assert "PLOSTON_RUNNER_TOKEN=plr_test" in content
        assert "KEY=value" in content


class TestLoadEnvFile:
    """Tests for load_env_file function."""

    def test_load_with_comments(self, tmp_path):
        """Test loading env file with comments."""
        env_file = tmp_path / ".env"
        env_file.write_text("""
# This is a comment
KEY1=value1
# Another comment
KEY2=value2
""")

        result = load_env_file(env_file)
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_load_with_inline_comments(self, tmp_path):
        """Test loading env file with inline comments."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value # inline comment\n")

        result = load_env_file(env_file)
        assert result == {"KEY": "value"}
