"""Integration tests for ploston init command."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ploston_cli.client import CPConnectionResult
from ploston_cli.main import cli


class TestInitCommandHelp:
    """Tests for init command help and basic invocation."""

    @pytest.fixture
    def runner(self):
        """Create CLI runner."""
        return CliRunner()

    def test_init_without_import_shows_usage(self, runner):
        """Test that init without --import shows usage."""
        result = runner.invoke(cli, ["init"])

        assert result.exit_code == 0
        assert "Usage: ploston init --import" in result.output

    def test_init_help(self, runner):
        """Test init --help."""
        result = runner.invoke(cli, ["init", "--help"])

        assert result.exit_code == 0
        assert "--import" in result.output
        assert "--source" in result.output
        assert "--cp-url" in result.output
        assert "--inject" in result.output
        assert "--non-interactive" in result.output


class TestInitImportNoConfig:
    """Tests for init --import when no config is found."""

    @pytest.fixture
    def runner(self):
        """Create CLI runner."""
        return CliRunner()

    def test_import_no_config_found(self, runner, tmp_path):
        """Test import when no Claude/Cursor config exists."""
        # Mock CP connectivity check to succeed
        mock_result = CPConnectionResult(
            connected=True, url="http://localhost:8022", version="1.0.0"
        )

        with patch("ploston_cli.commands.init.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.check_cp_connectivity = AsyncMock(return_value=mock_result)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            # Mock ConfigDetector to return no configs
            with patch("ploston_cli.commands.init.ConfigDetector") as mock_detector_class:
                mock_detector = mock_detector_class.return_value
                mock_detector.detect_all.return_value = []

                result = runner.invoke(cli, ["init", "--import", "--non-interactive"])

        assert result.exit_code == 1
        assert "No MCP configurations found" in result.output

    def test_import_reports_per_source_error_detail(self, runner, tmp_path):
        """Per-source errors (e.g. invalid JSON) must be surfaced, not hidden
        behind the generic 'No MCP configurations found' message. When a
        present-but-broken file exists, the 'install Claude/Cursor' hint must
        NOT be shown — it would contradict the per-source detail."""
        from pathlib import Path

        from ploston_cli.init.detector import DetectedConfig

        mock_result = CPConnectionResult(
            connected=True, url="http://localhost:8022", version="1.0.0"
        )

        # File exists on disk — represents the real-world "config present but
        # unparseable" scenario.
        broken_path = tmp_path / "claude_desktop_config.json"
        broken_path.write_text("{ not valid json")
        detected = [
            DetectedConfig(
                source="claude_desktop",
                path=broken_path,
                error="Invalid JSON: Expecting ',' delimiter: line 92 column 9 (char 2953)",
            ),
            DetectedConfig(
                source="cursor",
                path=Path("/missing/cursor"),
                error="Config not found at /missing/cursor",
            ),
        ]

        with patch("ploston_cli.commands.init.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.check_cp_connectivity = AsyncMock(return_value=mock_result)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with patch("ploston_cli.commands.init.ConfigDetector") as mock_detector_class:
                mock_detector = mock_detector_class.return_value
                mock_detector.detect_all.return_value = detected

                result = runner.invoke(cli, ["init", "--import", "--non-interactive"])

        assert result.exit_code == 1
        assert "No MCP configurations found" in result.output
        assert "Claude Desktop" in result.output
        assert "Invalid JSON" in result.output
        assert str(broken_path) in result.output
        assert "Cursor" in result.output
        assert "Config not found" in result.output
        # The install hint contradicts the per-source detail when a real file
        # exists, so it must be suppressed in this scenario.
        assert "Make sure Claude Desktop or Cursor is installed" not in result.output

    def test_import_shows_install_hint_when_all_sources_missing(self, runner, tmp_path):
        """When every source is genuinely absent (no file on disk anywhere),
        the 'install Claude/Cursor' hint is actionable and should be shown."""
        from pathlib import Path

        from ploston_cli.init.detector import DetectedConfig

        mock_result = CPConnectionResult(
            connected=True, url="http://localhost:8022", version="1.0.0"
        )

        detected = [
            DetectedConfig(
                source="claude_desktop",
                path=Path(str(tmp_path / "nope-claude.json")),
                error=f"Config not found at {tmp_path / 'nope-claude.json'}",
            ),
            DetectedConfig(
                source="cursor",
                path=Path(str(tmp_path / "nope-cursor")),
                error=f"Config not found at {tmp_path / 'nope-cursor'}",
            ),
        ]

        with patch("ploston_cli.commands.init.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.check_cp_connectivity = AsyncMock(return_value=mock_result)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with patch("ploston_cli.commands.init.ConfigDetector") as mock_detector_class:
                mock_detector = mock_detector_class.return_value
                mock_detector.detect_all.return_value = detected

                result = runner.invoke(cli, ["init", "--import", "--non-interactive"])

        assert result.exit_code == 1
        assert "No MCP configurations found" in result.output
        assert "Config not found" in result.output
        assert "Make sure Claude Desktop or Cursor is installed" in result.output


class TestInitImportWithConfig:
    """Tests for init --import with valid config."""

    @pytest.fixture
    def runner(self):
        """Create CLI runner."""
        return CliRunner()

    @pytest.fixture
    def mock_detected_config(self, tmp_path):
        """Create a mock detected config."""
        from ploston_cli.init.detector import DetectedConfig, ServerInfo

        config_file = tmp_path / "claude_config.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "filesystem": {"command": "npx", "args": ["@mcp/filesystem"]},
                    }
                }
            )
        )

        server = ServerInfo(
            name="filesystem",
            source="claude_desktop",
            command="npx",
            args=["@mcp/filesystem"],
        )

        return DetectedConfig(
            source="claude_desktop",
            path=config_file,
            servers={"filesystem": server},
            server_count=1,
        )

    def test_import_with_config_non_interactive(self, runner, mock_detected_config, tmp_path):
        """Test import with config in non-interactive mode."""
        # Mock CP connectivity
        mock_result = CPConnectionResult(
            connected=True, url="http://localhost:8022", version="1.0.0"
        )

        with patch("ploston_cli.commands.init.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.check_cp_connectivity = AsyncMock(return_value=mock_result)
            mock_client.push_runner_config = AsyncMock(return_value=None)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            # Mock ConfigDetector
            with patch("ploston_cli.commands.init.ConfigDetector") as mock_detector_class:
                mock_detector = mock_detector_class.return_value
                mock_detector.detect_all.return_value = [mock_detected_config]
                mock_detector.build_server_infos.return_value = [
                    mock_detected_config.servers["filesystem"]
                ]

                # Mock ServerSelector
                with patch("ploston_cli.commands.init.ServerSelector") as mock_selector_class:
                    mock_selector = mock_selector_class.return_value
                    mock_selector.select_all.return_value = ["filesystem"]

                    # Mock env file writing
                    env_file = tmp_path / ".ploston" / ".env"
                    with patch("ploston_cli.commands.init.write_env_file", return_value=env_file):
                        result = runner.invoke(
                            cli,
                            ["init", "--import", "--non-interactive"],
                        )

        assert result.exit_code == 0
        assert "Setup complete" in result.output
        assert "Imported 1 MCP servers to Ploston" in result.output


# ── §6.1 integration tests for TargetSelector wiring & backup flag ──────────


@dataclass
class _FakeDetected:
    source: str
    path: Path | None
    found: bool
    servers: dict | None = None
    server_count: int = 0


def _make_mock_cp():
    """Return mock_client for CP connectivity."""
    mock_result = CPConnectionResult(connected=True, url="http://localhost:8022", version="1.0.0")
    mock_client = AsyncMock()
    mock_client.check_cp_connectivity = AsyncMock(return_value=mock_result)
    mock_client.push_runner_config = AsyncMock(return_value=None)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


class TestTargetSelectorIntegration:
    """§6.1: TargetSelector wiring in the import flow."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.fixture
    def two_target_setup(self, tmp_path):
        """Two detected configs with one shared server."""
        from ploston_cli.init.detector import DetectedConfig, ServerInfo

        claude_cfg = tmp_path / "claude.json"
        claude_cfg.write_text(
            json.dumps({"mcpServers": {"github": {"command": "npx", "args": ["@mcp/github"]}}})
        )
        cursor_cfg = tmp_path / "cursor.json"
        cursor_cfg.write_text(
            json.dumps({"mcpServers": {"github": {"command": "npx", "args": ["@mcp/github"]}}})
        )

        server = ServerInfo(
            name="github", source="claude_desktop", command="npx", args=["@mcp/github"]
        )
        configs = [
            DetectedConfig(
                source="claude_desktop",
                path=claude_cfg,
                servers={"github": server},
                server_count=1,
            ),
            DetectedConfig(
                source="cursor",
                path=cursor_cfg,
                servers={"github": server},
                server_count=1,
            ),
        ]
        return configs, [server]

    def test_run_import_flow_with_inject_invokes_target_selector(
        self, runner, two_target_setup, tmp_path
    ):
        """--inject causes select_targets to be called inside the flow."""
        configs, servers = two_target_setup

        with patch("ploston_cli.commands.init.PlostClient") as mock_cls:
            mock_cls.return_value = _make_mock_cp()
            with patch("ploston_cli.commands.init.ConfigDetector") as det_cls:
                det = det_cls.return_value
                det.detect_all.return_value = configs
                det.build_server_infos.return_value = servers
                with patch("ploston_cli.commands.init.ServerSelector") as sel_cls:
                    sel_cls.return_value.select_all.return_value = ["github"]
                    with patch("ploston_cli.commands.init.select_targets") as mock_st:
                        mock_st.return_value = ["claude_desktop"]
                        with patch(
                            "ploston_cli.commands.init.write_env_file",
                            return_value=tmp_path / ".env",
                        ):
                            with patch("ploston_cli.commands.init.run_injection", return_value=[]):
                                result = runner.invoke(
                                    cli, ["init", "--import", "--inject", "--non-interactive"]
                                )

        assert result.exit_code == 0
        mock_st.assert_called_once()

    def test_inject_target_flag_bypasses_picker(self, runner, two_target_setup, tmp_path):
        """--inject-target <id> passes through to select_targets without prompting."""
        configs, servers = two_target_setup

        with patch("ploston_cli.commands.init.PlostClient") as mock_cls:
            mock_cls.return_value = _make_mock_cp()
            with patch("ploston_cli.commands.init.ConfigDetector") as det_cls:
                det = det_cls.return_value
                det.detect_all.return_value = configs
                det.build_server_infos.return_value = servers
                with patch("ploston_cli.commands.init.ServerSelector") as sel_cls:
                    sel_cls.return_value.select_all.return_value = ["github"]
                    with patch("ploston_cli.commands.init.select_targets") as mock_st:
                        mock_st.return_value = ["cursor"]
                        with patch(
                            "ploston_cli.commands.init.write_env_file",
                            return_value=tmp_path / ".env",
                        ):
                            with patch("ploston_cli.commands.init.run_injection", return_value=[]):
                                result = runner.invoke(
                                    cli,
                                    [
                                        "init",
                                        "--import",
                                        "--inject",
                                        "--inject-target",
                                        "cursor",
                                        "--non-interactive",
                                    ],
                                )

        assert result.exit_code == 0
        _, kwargs = mock_st.call_args
        assert kwargs.get("inject_targets") == ["cursor"]

    def test_non_interactive_inject_uses_contributors_only(
        self, runner, two_target_setup, tmp_path
    ):
        """Non-interactive mode feeds non_interactive=True into select_targets."""
        configs, servers = two_target_setup

        with patch("ploston_cli.commands.init.PlostClient") as mock_cls:
            mock_cls.return_value = _make_mock_cp()
            with patch("ploston_cli.commands.init.ConfigDetector") as det_cls:
                det = det_cls.return_value
                det.detect_all.return_value = configs
                det.build_server_infos.return_value = servers
                with patch("ploston_cli.commands.init.ServerSelector") as sel_cls:
                    sel_cls.return_value.select_all.return_value = ["github"]
                    with patch("ploston_cli.commands.init.select_targets") as mock_st:
                        mock_st.return_value = ["claude_desktop", "cursor"]
                        with patch(
                            "ploston_cli.commands.init.write_env_file",
                            return_value=tmp_path / ".env",
                        ):
                            with patch("ploston_cli.commands.init.run_injection", return_value=[]):
                                result = runner.invoke(
                                    cli, ["init", "--import", "--inject", "--non-interactive"]
                                )

        assert result.exit_code == 0
        _, kwargs = mock_st.call_args
        assert kwargs.get("non_interactive") is True


class TestNoBackupFileFlag:
    """§6.1: --no-backup-file flag wiring."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_no_backup_file_flag_skips_layer_2(self, runner, tmp_path):
        """--no-backup-file threads through to run_injection(no_backup_file=True)."""
        from ploston_cli.init.detector import DetectedConfig, ServerInfo

        cfg = tmp_path / "claude.json"
        cfg.write_text(
            json.dumps({"mcpServers": {"gh": {"command": "npx", "args": ["@mcp/github"]}}})
        )
        server = ServerInfo(name="gh", source="claude_desktop", command="npx", args=["@mcp/github"])
        configs = [
            DetectedConfig(
                source="claude_desktop", path=cfg, servers={"gh": server}, server_count=1
            )
        ]

        with patch("ploston_cli.commands.init.PlostClient") as mock_cls:
            mock_cls.return_value = _make_mock_cp()
            with patch("ploston_cli.commands.init.ConfigDetector") as det_cls:
                det = det_cls.return_value
                det.detect_all.return_value = configs
                det.build_server_infos.return_value = [server]
                with patch("ploston_cli.commands.init.ServerSelector") as sel_cls:
                    sel_cls.return_value.select_all.return_value = ["gh"]
                    with patch(
                        "ploston_cli.commands.init.select_targets", return_value=["claude_desktop"]
                    ):
                        with patch(
                            "ploston_cli.commands.init.write_env_file",
                            return_value=tmp_path / ".env",
                        ):
                            with patch("ploston_cli.commands.init.run_injection") as mock_ri:
                                mock_ri.return_value = []
                                result = runner.invoke(
                                    cli,
                                    [
                                        "init",
                                        "--import",
                                        "--inject",
                                        "--no-backup-file",
                                        "--non-interactive",
                                    ],
                                )

        assert result.exit_code == 0
        mock_ri.assert_called_once()
        _, kwargs = mock_ri.call_args
        assert kwargs.get("no_backup_file") is True
