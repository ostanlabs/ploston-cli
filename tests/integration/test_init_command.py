"""Integration tests for ploston init command."""

from __future__ import annotations

import json
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
            connected=True, url="http://localhost:8080", version="1.0.0"
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
            connected=True, url="http://localhost:8080", version="1.0.0"
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
        assert "Import Complete" in result.output
        assert "filesystem" in result.output or "1 servers" in result.output
