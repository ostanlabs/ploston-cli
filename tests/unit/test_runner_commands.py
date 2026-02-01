"""Unit tests for ploston runner commands.

Implements S-185: Runner CLI Commands
- UT-099: runner create command
- UT-100: runner list command
- UT-101: runner show command
- UT-102: runner delete command
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ploston_cli.client import PlostClientError
from ploston_cli.main import cli


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_runner_summary():
    """Create a mock runner summary dict."""
    return {
        "id": "runner_abc123",
        "name": "marc-laptop",
        "status": "connected",
        "last_seen": "2024-01-30T12:00:00Z",
        "tool_count": 5,
    }


@pytest.fixture
def mock_runner_detail():
    """Create a mock runner detail dict."""
    return {
        "id": "runner_abc123",
        "name": "marc-laptop",
        "status": "connected",
        "created_at": "2024-01-30T10:00:00Z",
        "last_seen": "2024-01-30T12:00:00Z",
        "available_tools": ["read_file", "write_file", "list_directory"],
        "mcps": {"native-tools": {"url": "http://localhost:8081"}},
    }


@pytest.fixture
def mock_create_response():
    """Create a mock runner creation response."""
    return {
        "id": "runner_abc123",
        "name": "marc-laptop",
        "token": "ploston_runner_abc123xyz",
        "install_command": "uv tool install ploston-runner && ploston-runner connect --token ploston_runner_abc123xyz --cp-url http://localhost:8080/runner/ws --name marc-laptop",
    }


class TestRunnerCreate:
    """Tests for ploston runner create command (UT-099).

    Note: Runner creation via CLI is no longer supported.
    Runners must be defined in the config file.
    """

    def test_runner_create_shows_error(self, runner):
        """Test that runner create shows helpful error message."""
        result = runner.invoke(cli, ["runner", "create", "marc-laptop"])

        assert result.exit_code == 1
        assert "no longer supported" in result.output
        assert "config file" in result.output
        assert "runners:" in result.output
        assert "marc-laptop" in result.output

    def test_runner_create_json_output_shows_error(self, runner):
        """Test that runner create with JSON flag still shows error."""
        result = runner.invoke(cli, ["--json", "runner", "create", "marc-laptop"])

        # Even with --json, we show the helpful error message
        assert result.exit_code == 1
        assert "no longer supported" in result.output


class TestRunnerList:
    """Tests for ploston runner list command (UT-100)."""

    def test_runner_list_shows_all_runners(self, runner, mock_runner_summary):
        """Test that runner list shows all runners."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_runners = AsyncMock(return_value=[mock_runner_summary])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["runner", "list"])

            assert result.exit_code == 0
            assert "marc-laptop" in result.output
            assert "Total runners: 1" in result.output
            mock_client.list_runners.assert_called_once_with(status=None)

    def test_runner_list_filter_by_status(self, runner, mock_runner_summary):
        """Test filtering runners by status."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_runners = AsyncMock(return_value=[mock_runner_summary])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["runner", "list", "--status", "connected"])

            assert result.exit_code == 0
            mock_client.list_runners.assert_called_once_with(status="connected")

    def test_runner_list_empty(self, runner):
        """Test empty runner list."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_runners = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["runner", "list"])

            assert result.exit_code == 0
            assert "No runners registered" in result.output

    def test_runner_list_json_output(self, runner, mock_runner_summary):
        """Test JSON output format for runner list."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_runners = AsyncMock(return_value=[mock_runner_summary])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["--json", "runner", "list"])

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["total"] == 1
            assert data["runners"][0]["name"] == "marc-laptop"


class TestRunnerShow:
    """Tests for ploston runner show command (UT-101)."""

    def test_runner_show_existing(self, runner, mock_runner_detail):
        """Test showing an existing runner."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_runner = AsyncMock(return_value=mock_runner_detail)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["runner", "show", "marc-laptop"])

            assert result.exit_code == 0
            assert "marc-laptop" in result.output
            assert "runner_abc123" in result.output
            assert "read_file" in result.output

    def test_runner_show_not_found(self, runner):
        """Test showing a non-existent runner."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_runner = AsyncMock(
                side_effect=PlostClientError("Runner not found", status_code=404)
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["runner", "show", "unknown"])

            assert result.exit_code == 1
            assert "not found" in result.output

    def test_runner_show_json_output(self, runner, mock_runner_detail):
        """Test JSON output format for runner show."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_runner = AsyncMock(return_value=mock_runner_detail)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["--json", "runner", "show", "marc-laptop"])

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["name"] == "marc-laptop"
            assert data["id"] == "runner_abc123"
            assert "read_file" in data["available_tools"]


class TestRunnerDelete:
    """Tests for ploston runner delete command (UT-102)."""

    def test_runner_delete_success(self, runner):
        """Test successful runner deletion with force flag."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.delete_runner = AsyncMock(
                return_value={"deleted": True, "name": "marc-laptop"}
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["runner", "delete", "marc-laptop", "--force"])

            assert result.exit_code == 0
            assert "deleted" in result.output
            mock_client.delete_runner.assert_called_once_with("marc-laptop")

    def test_runner_delete_with_confirmation(self, runner):
        """Test runner deletion with confirmation prompt."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.delete_runner = AsyncMock(
                return_value={"deleted": True, "name": "marc-laptop"}
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            # Simulate user confirming with 'y'
            result = runner.invoke(cli, ["runner", "delete", "marc-laptop"], input="y\n")

            assert result.exit_code == 0
            assert "deleted" in result.output

    def test_runner_delete_cancelled(self, runner):
        """Test runner deletion cancelled by user."""
        # Simulate user declining with 'n'
        result = runner.invoke(cli, ["runner", "delete", "marc-laptop"], input="n\n")

        assert result.exit_code == 1  # Aborted

    def test_runner_delete_not_found(self, runner):
        """Test deleting a non-existent runner."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.delete_runner = AsyncMock(
                side_effect=PlostClientError("Runner 'unknown' not found", status_code=404)
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["runner", "delete", "unknown", "--force"])

            assert result.exit_code == 1
            assert "not found" in result.output

    def test_runner_delete_json_output(self, runner):
        """Test JSON output format for runner delete."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.delete_runner = AsyncMock(
                return_value={"deleted": True, "name": "marc-laptop"}
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["--json", "runner", "delete", "marc-laptop", "--force"])

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["deleted"] is True
            assert data["name"] == "marc-laptop"


class TestRunnerGetToken:
    """Tests for ploston runner get-token command."""

    def test_get_token_shows_error(self, runner):
        """Test that get-token shows helpful error about security."""
        result = runner.invoke(cli, ["runner", "get-token", "marc-laptop"])

        assert result.exit_code == 1
        assert "not stored" in result.output
        assert "security" in result.output
        assert "regenerate-token" in result.output


class TestRunnerRegenerateToken:
    """Tests for ploston runner regenerate-token command."""

    def test_regenerate_token_success(self, runner):
        """Test successful token regeneration with force flag."""
        mock_response = {
            "name": "marc-laptop",
            "token": "ploston_runner_newtoken123",
            "install_command": "ploston-runner install --cp-url http://localhost:8080 --token ploston_runner_newtoken123",
        }
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.regenerate_runner_token = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["runner", "regenerate-token", "marc-laptop", "--force"])

            assert result.exit_code == 0
            assert "regenerated" in result.output.lower()
            assert "ploston_runner_newtoken123" in result.output
            mock_client.regenerate_runner_token.assert_called_once_with("marc-laptop")

    def test_regenerate_token_with_confirmation(self, runner):
        """Test token regeneration with confirmation prompt."""
        mock_response = {
            "name": "marc-laptop",
            "token": "ploston_runner_newtoken123",
            "install_command": "ploston-runner install --cp-url http://localhost:8080 --token ploston_runner_newtoken123",
        }
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.regenerate_runner_token = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["runner", "regenerate-token", "marc-laptop"], input="y\n")

            assert result.exit_code == 0
            assert "ploston_runner_newtoken123" in result.output

    def test_regenerate_token_cancelled(self, runner):
        """Test token regeneration cancelled by user."""
        result = runner.invoke(cli, ["runner", "regenerate-token", "marc-laptop"], input="n\n")

        assert result.exit_code == 1  # Aborted

    def test_regenerate_token_not_found(self, runner):
        """Test regenerating token for non-existent runner."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.regenerate_runner_token = AsyncMock(
                side_effect=PlostClientError("Runner 'unknown' not found", status_code=404)
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["runner", "regenerate-token", "unknown", "--force"])

            assert result.exit_code == 1
            assert "not found" in result.output

    def test_regenerate_token_json_output(self, runner):
        """Test JSON output format for token regeneration."""
        mock_response = {
            "name": "marc-laptop",
            "token": "ploston_runner_newtoken123",
            "install_command": "ploston-runner install --cp-url http://localhost:8080 --token ploston_runner_newtoken123",
        }
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.regenerate_runner_token = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(
                cli, ["--json", "runner", "regenerate-token", "marc-laptop", "--force"]
            )

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["name"] == "marc-laptop"
            assert data["token"] == "ploston_runner_newtoken123"
            assert "install_command" in data
