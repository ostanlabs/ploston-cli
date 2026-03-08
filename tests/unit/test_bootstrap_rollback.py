"""Unit tests for `ploston bootstrap rollback` command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ploston_cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


def _mock_detected_config(config_path: Path, source: str = "claude_desktop"):
    """Build a DetectedConfig-like mock."""
    cfg = MagicMock()
    cfg.path = config_path
    cfg.source = source
    cfg.found = True
    return cfg


class TestBootstrapRollback:
    """Tests for the `ploston bootstrap rollback` command."""

    def test_rollback_restores_from_backup(self, runner, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        injected = {
            "mcpServers": {
                "github-via-ploston": {
                    "command": "ploston",
                    "args": ["bridge", "--expose", "github"],
                },
                "ploston": {
                    "command": "ploston",
                    "args": ["bridge", "--expose", "workflows"],
                },
            },
            "_ploston_imported": {
                "github": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "ghp_abc123"},
                }
            },
        }
        config_path.write_text(json.dumps(injected, indent=2))

        original = {
            "mcpServers": {
                "github": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "ghp_abc123"},
                }
            }
        }
        backup_path = tmp_path / "claude_desktop_config.backup_20250101_120000.json"
        backup_path.write_text(json.dumps(original, indent=2))

        with patch("ploston_cli.commands.bootstrap.ConfigDetector") as mock_detector:
            mock_detector.return_value.detect_all.return_value = [
                _mock_detected_config(config_path)
            ]
            result = runner.invoke(cli, ["bootstrap", "rollback"])

        assert result.exit_code == 0
        assert "Restored Claude Desktop config from backup" in result.output
        assert "1 config(s) restored" in result.output

        restored = json.loads(config_path.read_text())
        assert "github" in restored["mcpServers"]
        assert "_ploston_imported" not in restored

    def test_rollback_no_injection_is_noop(self, runner, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.write_text(json.dumps({"mcpServers": {"github": {}}}))

        with patch("ploston_cli.commands.bootstrap.ConfigDetector") as mock_detector:
            mock_detector.return_value.detect_all.return_value = [
                _mock_detected_config(config_path)
            ]
            result = runner.invoke(cli, ["bootstrap", "rollback"])

        assert result.exit_code == 0
        assert "nothing to roll back" in result.output.lower()

    def test_rollback_no_backup_warns(self, runner, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        injected = {
            "mcpServers": {
                "github-via-ploston": {
                    "command": "ploston",
                    "args": ["bridge", "--expose", "github"],
                },
                "ploston": {
                    "command": "ploston",
                    "args": ["bridge", "--expose", "workflows"],
                },
            },
            "_ploston_imported": {"github": {}},
        }
        config_path.write_text(json.dumps(injected, indent=2))

        with patch("ploston_cli.commands.bootstrap.ConfigDetector") as mock_detector:
            mock_detector.return_value.detect_all.return_value = [
                _mock_detected_config(config_path)
            ]
            result = runner.invoke(cli, ["bootstrap", "rollback"])

        assert result.exit_code == 0
        assert "no backup found" in result.output.lower()
        assert "_ploston_imported" in result.output

    def test_rollback_no_configs_detected(self, runner):
        with patch("ploston_cli.commands.bootstrap.ConfigDetector") as mock_detector:
            mock_detector.return_value.detect_all.return_value = []
            result = runner.invoke(cli, ["bootstrap", "rollback"])

        assert result.exit_code == 0
        assert "nothing to roll back" in result.output.lower()
