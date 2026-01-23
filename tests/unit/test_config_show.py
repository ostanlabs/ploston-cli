"""Unit tests for ael config show command."""

import json

import pytest
from click.testing import CliRunner

from ploston_cli.main import cli


class TestConfigShow:
    """Tests for ael config show command."""

    @pytest.fixture
    def runner(self):
        """Create CLI runner."""
        return CliRunner()

    @pytest.fixture
    def config_file(self, tmp_path):
        """Create a test config file."""
        config_path = tmp_path / "ael-config.yaml"
        config_path.write_text("""
server:
  port: 8080
  host: localhost

logging:
  level: INFO

execution:
  default_timeout: 300
""")
        return config_path

    def test_config_show_full(self, runner, config_file):
        """Test showing full configuration."""
        result = runner.invoke(cli, ["-c", str(config_file), "config", "show"])

        assert result.exit_code == 0
        assert "AEL Configuration" in result.output
        assert "server:" in result.output
        assert "port: 8080" in result.output

    def test_config_show_section(self, runner, config_file):
        """Test showing specific section."""
        result = runner.invoke(
            cli, ["-c", str(config_file), "config", "show", "--section", "server"]
        )

        assert result.exit_code == 0
        assert "server:" in result.output
        assert "port: 8080" in result.output
        # Should not show other sections
        assert "logging:" not in result.output

    def test_config_show_invalid_section(self, runner, config_file):
        """Test showing invalid section."""
        result = runner.invoke(
            cli, ["-c", str(config_file), "config", "show", "--section", "invalid"]
        )

        assert result.exit_code == 1
        assert "Unknown section 'invalid'" in result.output
        assert "Valid sections:" in result.output

    def test_config_show_json(self, runner, config_file):
        """Test JSON output."""
        result = runner.invoke(cli, ["--json", "-c", str(config_file), "config", "show"])

        assert result.exit_code == 0
        # Should be valid JSON
        data = json.loads(result.output)
        assert "server" in data
        assert data["server"]["port"] == 8080

    def test_config_show_json_section(self, runner, config_file):
        """Test JSON output for specific section."""
        result = runner.invoke(
            cli, ["--json", "-c", str(config_file), "config", "show", "--section", "server"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "port" in data
        assert data["port"] == 8080

    def test_config_show_no_config(self, runner, tmp_path):
        """Test error when no config file exists."""
        # Use a non-existent path
        result = runner.invoke(cli, ["-c", str(tmp_path / "nonexistent.yaml"), "config", "show"])

        assert result.exit_code == 1
        assert "Error:" in result.output


class TestValidSections:
    """Tests for valid sections list."""

    def test_all_valid_sections(self, tmp_path):
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
