"""Unit tests for ploston config show command."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ploston_cli.main import cli


class TestConfigShowLocal:
    """Tests for ploston config show --local command."""

    @pytest.fixture
    def runner(self):
        """Create CLI runner."""
        return CliRunner()

    def test_config_show_local(self, runner, tmp_path):
        """Test showing local CLI configuration."""
        # Create a local config file
        config_dir = tmp_path / ".ploston"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text("server: http://custom:9000\ntimeout: 60\n")

        with patch("ploston_cli.config.get_config_path", return_value=config_file):
            result = runner.invoke(cli, ["config", "show", "--local"])

        assert result.exit_code == 0
        assert "Ploston CLI Configuration" in result.output
        assert "http://custom:9000" in result.output

    def test_config_show_local_json(self, runner, tmp_path):
        """Test JSON output for local config."""
        config_dir = tmp_path / ".ploston"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text("server: http://custom:9000\n")

        with patch("ploston_cli.config.get_config_path", return_value=config_file):
            result = runner.invoke(cli, ["--json", "config", "show", "--local"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "values" in data
        assert data["values"]["server"] == "http://custom:9000"


class TestConfigShowServer:
    """Tests for ploston config show (server config)."""

    @pytest.fixture
    def runner(self):
        """Create CLI runner."""
        return CliRunner()

    def test_config_show_server(self, runner):
        """Test showing server configuration."""
        mock_config = {
            "server": {"port": 8080, "host": "localhost"},
            "logging": {"level": "INFO"},
        }

        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_config = AsyncMock(return_value=mock_config)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["config", "show"])

        assert result.exit_code == 0
        assert "Ploston Server Configuration" in result.output

    def test_config_show_invalid_section(self, runner):
        """Test showing invalid section."""
        result = runner.invoke(cli, ["config", "show", "--section", "invalid"])

        assert result.exit_code == 1
        assert "Unknown section 'invalid'" in result.output
        assert "Valid sections:" in result.output


class TestConfigSet:
    """Tests for ploston config set command."""

    @pytest.fixture
    def runner(self):
        """Create CLI runner."""
        return CliRunner()

    def test_config_set_server(self, runner, tmp_path):
        """Test setting server URL."""
        config_dir = tmp_path / ".ploston"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"

        with patch("ploston_cli.config.get_config_path", return_value=config_file):
            result = runner.invoke(cli, ["config", "set", "server", "http://new:8080"])

        assert result.exit_code == 0
        assert "Set server = http://new:8080" in result.output

    def test_config_set_timeout_invalid(self, runner):
        """Test setting invalid timeout."""
        result = runner.invoke(cli, ["config", "set", "timeout", "not-a-number"])

        assert result.exit_code == 1
        assert "timeout must be an integer" in result.output


class TestValidSections:
    """Tests for valid sections list."""

    def test_all_valid_sections(self):
        """Test all valid sections are accepted."""
        from ploston_cli.main import VALID_SECTIONS

        expected = [
            "server",
            "mcp",
            "tools",
            "workflows",
            "execution",
            "python_exec",
            "logging",
            "plugins",
            "security",
            "telemetry",
        ]

        assert VALID_SECTIONS == expected
