"""Unit tests for ael tools list command."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner
from ploston_core.types import ToolSource, ToolStatus

from ploston_cli.main import cli


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_tool():
    """Create a mock tool definition."""
    tool = MagicMock()
    tool.name = "test_tool"
    tool.description = "A test tool for testing"
    tool.source = ToolSource.MCP
    tool.server_name = "test_server"
    tool.status = ToolStatus.AVAILABLE
    tool.input_schema = {"type": "object", "properties": {}}
    return tool


@pytest.fixture
def mock_system_tool():
    """Create a mock system tool."""
    tool = MagicMock()
    tool.name = "python_exec"
    tool.description = "Execute Python code"
    tool.source = ToolSource.SYSTEM
    tool.server_name = None
    tool.status = ToolStatus.AVAILABLE
    tool.input_schema = {}
    return tool


class TestToolsList:
    """Tests for ael tools list command."""

    def test_tools_list_shows_all_tools(self, runner, mock_tool, mock_system_tool):
        """Test that tools list shows all tools."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()
            mock_app.tool_registry.list_tools.return_value = [mock_tool, mock_system_tool]
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["tools", "list"])

            assert result.exit_code == 0
            assert "test_tool" in result.output
            assert "python_exec" in result.output
            assert "test_server" in result.output
            assert "System Tools" in result.output

    def test_tools_list_filter_by_source(self, runner, mock_tool):
        """Test filtering by source."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()
            mock_app.tool_registry.list_tools.return_value = [mock_tool]
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["tools", "list", "--source", "mcp"])

            assert result.exit_code == 0
            mock_app.tool_registry.list_tools.assert_called_once_with(
                source=ToolSource.MCP,
                server_name=None,
                status=None,
            )

    def test_tools_list_filter_by_server(self, runner, mock_tool):
        """Test filtering by server name."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()
            mock_app.tool_registry.list_tools.return_value = [mock_tool]
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["tools", "list", "--server", "test_server"])

            assert result.exit_code == 0
            mock_app.tool_registry.list_tools.assert_called_once_with(
                source=None,
                server_name="test_server",
                status=None,
            )

    def test_tools_list_filter_by_status(self, runner, mock_tool):
        """Test filtering by status."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()
            mock_app.tool_registry.list_tools.return_value = [mock_tool]
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["tools", "list", "--status", "available"])

            assert result.exit_code == 0
            mock_app.tool_registry.list_tools.assert_called_once_with(
                source=None,
                server_name=None,
                status=ToolStatus.AVAILABLE,
            )

    def test_tools_list_json_output(self, runner, mock_tool):
        """Test JSON output format."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()
            mock_app.tool_registry.list_tools.return_value = [mock_tool]
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["--json", "tools", "list"])

            assert result.exit_code == 0
            import json

            data = json.loads(result.output)
            assert len(data) == 1
            assert data[0]["name"] == "test_tool"
            assert data[0]["source"] == "mcp"
            assert data[0]["status"] == "available"

    def test_tools_list_empty(self, runner):
        """Test empty tools list."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()
            mock_app.tool_registry.list_tools.return_value = []
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["tools", "list"])

            assert result.exit_code == 0
            assert "0 total" in result.output


class TestToolsShow:
    """Tests for ael tools show command."""

    def test_tools_show_existing_tool(self, runner, mock_tool):
        """Test showing an existing tool."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()
            mock_app.tool_registry.get.return_value = mock_tool
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["tools", "show", "test_tool"])

            assert result.exit_code == 0
            assert "test_tool" in result.output
            assert "test_server" in result.output
            assert "Available" in result.output

    def test_tools_show_not_found_with_suggestions(self, runner, mock_tool):
        """Test showing a non-existent tool with suggestions."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()
            mock_app.tool_registry.get.return_value = None
            mock_app.tool_registry.search.return_value = [mock_tool]
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["tools", "show", "unknown_tool"])

            assert result.exit_code == 1
            assert "not found" in result.output
            assert "Did you mean" in result.output
            assert "test_tool" in result.output

    def test_tools_show_not_found_no_suggestions(self, runner):
        """Test showing a non-existent tool without suggestions."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()
            mock_app.tool_registry.get.return_value = None
            mock_app.tool_registry.search.return_value = []
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["tools", "show", "unknown_tool"])

            assert result.exit_code == 1
            assert "not found" in result.output
            assert "Did you mean" not in result.output

    def test_tools_show_json_output(self, runner, mock_tool):
        """Test JSON output format for tools show."""
        mock_tool.output_schema = {"type": "object"}
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()
            mock_app.tool_registry.get.return_value = mock_tool
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["--json", "tools", "show", "test_tool"])

            assert result.exit_code == 0
            import json

            data = json.loads(result.output)
            assert data["name"] == "test_tool"
            assert data["source"] == "mcp"
            assert data["input_schema"] is not None


class TestToolsRefresh:
    """Tests for ael tools refresh command."""

    def test_tools_refresh_all(self, runner):
        """Test refreshing all tools."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()

            mock_result = MagicMock()
            mock_result.total_tools = 10
            mock_result.added = ["new_tool"]
            mock_result.removed = []
            mock_result.updated = ["updated_tool"]
            mock_result.errors = {}
            mock_app.tool_registry.refresh = AsyncMock(return_value=mock_result)
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["tools", "refresh"])

            assert result.exit_code == 0
            assert "Refreshing tools" in result.output
            assert "Total tools: 10" in result.output
            assert "Added: 1" in result.output
            mock_app.tool_registry.refresh.assert_called_once()

    def test_tools_refresh_specific_server(self, runner):
        """Test refreshing a specific server."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()

            mock_result = MagicMock()
            mock_result.total_tools = 5
            mock_result.added = []
            mock_result.removed = []
            mock_result.updated = []
            mock_result.errors = {}
            mock_app.tool_registry.refresh_server = AsyncMock(return_value=mock_result)
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["tools", "refresh", "--server", "test_server"])

            assert result.exit_code == 0
            mock_app.tool_registry.refresh_server.assert_called_once_with("test_server")

    def test_tools_refresh_with_errors(self, runner):
        """Test refresh with errors."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()

            mock_result = MagicMock()
            mock_result.total_tools = 5
            mock_result.added = []
            mock_result.removed = []
            mock_result.updated = []
            mock_result.errors = {"failed_server": "Connection refused"}
            mock_app.tool_registry.refresh = AsyncMock(return_value=mock_result)
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["tools", "refresh"])

            assert result.exit_code == 0
            assert "Errors" in result.output
            assert "failed_server" in result.output

    def test_tools_refresh_json_output(self, runner):
        """Test JSON output for refresh."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.tool_registry = MagicMock()

            mock_result = MagicMock()
            mock_result.total_tools = 10
            mock_result.added = ["new_tool"]
            mock_result.removed = []
            mock_result.updated = []
            mock_result.errors = {}
            mock_app.tool_registry.refresh = AsyncMock(return_value=mock_result)
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["--json", "tools", "refresh"])

            assert result.exit_code == 0
            import json

            # Skip the "Refreshing tools..." line
            lines = result.output.strip().split("\n")
            json_output = "\n".join(lines[1:])
            data = json.loads(json_output)
            assert data["total_tools"] == 10
            assert "new_tool" in data["added"]
