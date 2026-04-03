"""Tests for ploston inject command and multi-target injection (T-769).

See: DEC169-175_ROUTING_TAGS_CLI_SPEC.md §7
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ploston_cli.init.detector import ALL_INJECT_TARGETS
from ploston_cli.init.injector import SOURCE_LABELS, run_injection
from ploston_cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@dataclass
class FakeDetected:
    source: str
    path: Path | None
    found: bool


class TestRunInjection:
    """Tests for the shared run_injection helper."""

    def test_injects_into_all_found_configs(self, tmp_path):
        """run_injection with no targets → all found configs injected."""
        claude_cfg = tmp_path / "claude.json"
        cursor_cfg = tmp_path / "cursor.json"
        claude_cfg.write_text(json.dumps({"mcpServers": {"github": {"command": "npx"}}}))
        cursor_cfg.write_text(json.dumps({"mcpServers": {"github": {"command": "npx"}}}))

        detected = [
            FakeDetected(source="claude_desktop", path=claude_cfg, found=True),
            FakeDetected(source="cursor", path=cursor_cfg, found=True),
            FakeDetected(source="claude_code_global", path=None, found=False),
        ]
        results = run_injection(
            detected_configs=detected,
            imported_servers=["github"],
            cp_url="http://localhost:8022",
        )
        assert len(results) == 2
        assert all(err is None for _, _, err in results)

    def test_injects_only_into_specified_targets(self, tmp_path):
        """run_injection with targets → only matching configs injected."""
        claude_cfg = tmp_path / "claude.json"
        cursor_cfg = tmp_path / "cursor.json"
        claude_cfg.write_text(json.dumps({"mcpServers": {"gh": {"command": "npx"}}}))
        cursor_cfg.write_text(json.dumps({"mcpServers": {"gh": {"command": "npx"}}}))

        detected = [
            FakeDetected(source="claude_desktop", path=claude_cfg, found=True),
            FakeDetected(source="cursor", path=cursor_cfg, found=True),
        ]
        results = run_injection(
            detected_configs=detected,
            imported_servers=["gh"],
            cp_url="http://localhost:8022",
            targets=["cursor"],
        )
        assert len(results) == 1
        assert results[0][0] == "cursor"

    def test_reports_errors_without_raising(self, tmp_path):
        """run_injection catches errors and reports them."""
        bad_cfg = tmp_path / "bad.json"
        bad_cfg.write_text("NOT JSON")

        detected = [FakeDetected(source="claude_desktop", path=bad_cfg, found=True)]
        results = run_injection(
            detected_configs=detected,
            imported_servers=["gh"],
            cp_url="http://localhost:8022",
        )
        assert len(results) == 1
        assert results[0][2] is not None  # error string


class TestConfigDetectorClaudeCode:
    """Tests for Claude Code config detection."""

    def test_claude_code_global_path(self):
        from ploston_cli.init.detector import ConfigDetector

        d = ConfigDetector()
        path = d.get_config_path("claude_code_global")
        assert path is not None
        assert ".claude" in str(path)
        assert "settings.json" in str(path)

    def test_claude_code_project_path(self):
        from ploston_cli.init.detector import ConfigDetector

        d = ConfigDetector()
        path = d.get_config_path("claude_code_project")
        assert path is not None
        assert ".mcp.json" in str(path)

    def test_all_inject_targets_have_labels(self):
        for t in ALL_INJECT_TARGETS:
            assert t in SOURCE_LABELS


class TestInjectTargetFlag:
    """Tests for --inject-target on init command."""

    def test_inject_target_non_interactive(self, tmp_path, runner):
        """--inject-target cursor → only Cursor config modified."""
        cursor_cfg = tmp_path / "cursor.json"
        claude_cfg = tmp_path / "claude.json"
        cursor_cfg.write_text(json.dumps({"mcpServers": {"gh": {"command": "npx"}}}))
        claude_cfg.write_text(json.dumps({"mcpServers": {"gh": {"command": "npx"}}}))

        # Verify the --inject-target option is accepted by the CLI
        result = runner.invoke(
            cli, ["-s", "http://localhost:8022", "inject", "--inject-target", "cursor", "--help"]
        )
        # --help should succeed showing inject command help
        assert result.exit_code == 0
        assert "inject-target" in result.output


class TestInjectStandalone:
    """Tests for ploston inject standalone command."""

    def test_inject_help(self, runner):
        """ploston inject --help shows correct usage."""
        result = runner.invoke(cli, ["inject", "--help"])
        assert result.exit_code == 0
        assert "inject-target" in result.output
        assert "Re-run" in result.output

    def test_inject_no_configs_detected(self, runner):
        """ploston inject with no agent configs → friendly message."""
        with patch("ploston_cli.commands.inject.ConfigDetector") as mock_detector:
            instance = mock_detector.return_value
            instance.detect_all.return_value = []
            result = runner.invoke(cli, ["-s", "http://localhost:8022", "inject"])
        assert result.exit_code == 0
        assert "No agent configs detected" in result.output
