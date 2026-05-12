"""Tests for Layer-2 file backup (T-1006)."""

from __future__ import annotations

import os

import pytest

from ploston_cli.init.backup import (
    _BACKUP_PATTERN,
    _has_existing_backup,
    find_latest_backup,
    is_backup_file,
    make_backup,
    restore_from_backup,
)


@pytest.fixture()
def config_file(tmp_path):
    """Create a simple config file for backup tests."""
    cfg = tmp_path / "mcp.json"
    cfg.write_text('{"mcpServers":{}}', encoding="utf-8")
    return cfg


class TestMakeBackup:
    def test_creates_backup(self, config_file):
        result = make_backup(config_file)
        assert result is not None
        assert result.exists()
        assert result.read_text(encoding="utf-8") == '{"mcpServers":{}}'

    def test_idempotent_second_call_returns_none(self, config_file):
        first = make_backup(config_file)
        assert first is not None
        second = make_backup(config_file)
        assert second is None  # already exists

    def test_preserves_permissions(self, config_file):
        os.chmod(config_file, 0o600)
        result = make_backup(config_file)
        assert result is not None
        assert oct(result.stat().st_mode & 0o777) == oct(0o600)

    def test_returns_none_for_missing_file(self, tmp_path):
        assert make_backup(tmp_path / "nonexistent.json") is None

    def test_backup_filename_matches_pattern(self, config_file):
        result = make_backup(config_file)
        assert result is not None
        assert _BACKUP_PATTERN.search(result.name)


class TestFindLatestBackup:
    def test_returns_none_when_no_backup(self, config_file):
        assert find_latest_backup(config_file) is None

    def test_returns_backup_after_creation(self, config_file):
        backup = make_backup(config_file)
        found = find_latest_backup(config_file)
        assert found == backup

    def test_returns_latest_of_multiple(self, config_file):
        # Create two backups by hand with different timestamps
        parent = config_file.parent
        name = config_file.name
        b1 = parent / f"{name}.ploston-backup-2025-01-01T00-00-00Z"
        b2 = parent / f"{name}.ploston-backup-2025-06-01T00-00-00Z"
        b1.write_text("old")
        b2.write_text("new")
        assert find_latest_backup(config_file) == b2


class TestRestoreFromBackup:
    def test_restores_content(self, config_file):
        make_backup(config_file)
        # Now modify the live config
        config_file.write_text('{"modified": true}', encoding="utf-8")
        assert restore_from_backup(config_file) is True
        assert config_file.read_text(encoding="utf-8") == '{"mcpServers":{}}'

    def test_returns_false_when_no_backup(self, config_file):
        assert restore_from_backup(config_file) is False


class TestIsBackupFile:
    def test_positive(self, tmp_path):
        p = tmp_path / "mcp.json.ploston-backup-2025-06-01T12-00-00Z"
        assert is_backup_file(p) is True

    def test_negative(self, tmp_path):
        p = tmp_path / "mcp.json"
        assert is_backup_file(p) is False


class TestHasExistingBackup:
    def test_no_backup(self, config_file):
        assert _has_existing_backup(config_file) is False

    def test_with_backup(self, config_file):
        make_backup(config_file)
        assert _has_existing_backup(config_file) is True
