"""Unit tests for ploston tools list command."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ploston_cli.main import cli


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_tool():
    """Create a mock tool dict."""
    return {
        "name": "test_tool",
        "description": "A test tool for testing",
        "source": "mcp",
        "server_name": "test_server",
        "status": "available",
        "input_schema": {"type": "object", "properties": {}},
    }


@pytest.fixture
def mock_system_tool():
    """Create a mock system tool dict."""
    return {
        "name": "python_exec",
        "description": "Execute Python code",
        "source": "system",
        "server_name": None,
        "status": "available",
        "input_schema": {},
    }


class TestToolsList:
    """Tests for ploston tools list command."""

    def test_tools_list_shows_all_tools(self, runner, mock_tool, mock_system_tool):
        """Test that tools list shows all tools."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_tool, mock_system_tool])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["tools", "list"])

            assert result.exit_code == 0
            assert "test_tool" in result.output
            assert "python_exec" in result.output
            assert "test_server" in result.output
            assert "System Tools" in result.output

    def test_tools_list_json_output(self, runner, mock_tool):
        """Test JSON output format."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_tool])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["--json", "tools", "list"])

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 1
            assert data[0]["name"] == "test_tool"
            assert data[0]["source"] == "mcp"
            assert data[0]["status"] == "available"

    def test_tools_list_empty(self, runner):
        """Test empty tools list."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["tools", "list"])

            assert result.exit_code == 0
            assert "0 total" in result.output


class TestToolsShow:
    """Tests for ploston tools show command."""

    def test_tools_show_existing_tool(self, runner, mock_tool):
        """Test showing an existing tool."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_tool = AsyncMock(return_value=mock_tool)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["tools", "show", "test_tool"])

            assert result.exit_code == 0
            assert "test_tool" in result.output
            assert "test_server" in result.output
            assert "Available" in result.output

    def test_tools_show_not_found(self, runner):
        """Test showing a non-existent tool."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_tool = AsyncMock(return_value=None)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["tools", "show", "unknown_tool"])

            assert result.exit_code == 1
            assert "not found" in result.output

    def test_tools_show_json_output(self, runner, mock_tool):
        """Test JSON output format for tools show."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_tool = AsyncMock(return_value=mock_tool)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["--json", "tools", "show", "test_tool"])

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["name"] == "test_tool"
            assert data["source"] == "mcp"
            assert data["input_schema"] is not None


class TestToolsRefresh:
    """Tests for ploston tools refresh command."""

    def test_tools_refresh_all(self, runner):
        """Test refreshing all tools."""
        mock_result = {
            "total_tools": 10,
            "added": ["new_tool"],
            "removed": [],
            "updated": ["updated_tool"],
            "errors": {},
        }

        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.refresh_tools = AsyncMock(return_value=mock_result)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["tools", "refresh"])

            assert result.exit_code == 0
            assert "Refreshing tools" in result.output
            assert "Total tools: 10" in result.output
            assert "Added: 1" in result.output

    def test_tools_refresh_with_errors(self, runner):
        """Test refresh with errors."""
        mock_result = {
            "total_tools": 5,
            "added": [],
            "removed": [],
            "updated": [],
            "errors": {"failed_server": "Connection refused"},
        }

        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.refresh_tools = AsyncMock(return_value=mock_result)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["tools", "refresh"])

            assert result.exit_code == 0
            assert "Errors" in result.output
            assert "failed_server" in result.output

    def test_tools_refresh_json_output(self, runner):
        """Test JSON output for refresh."""
        mock_result = {
            "total_tools": 10,
            "added": ["new_tool"],
            "removed": [],
            "updated": [],
            "errors": {},
        }

        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.refresh_tools = AsyncMock(return_value=mock_result)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["--json", "tools", "refresh"])

            assert result.exit_code == 0
            # Skip the "Refreshing tools..." line
            lines = result.output.strip().split("\n")
            json_output = "\n".join(lines[1:])
            data = json.loads(json_output)
            assert data["total_tools"] == 10
            assert "new_tool" in data["added"]
