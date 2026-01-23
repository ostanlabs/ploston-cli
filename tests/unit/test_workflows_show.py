"""Unit tests for ploston workflows show command."""

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
def mock_workflow():
    """Create a mock workflow dict."""
    return {
        "name": "test-workflow",
        "version": "1.0.0",
        "description": "A test workflow",
        "inputs": [
            {
                "name": "url",
                "type": "string",
                "required": True,
                "default": None,
                "description": "URL to process",
            },
            {
                "name": "timeout",
                "type": "integer",
                "required": False,
                "default": 30,
                "description": "Timeout in seconds",
            },
        ],
        "steps": [
            {"id": "fetch", "tool": "http_request", "code": None},
            {"id": "transform", "tool": None, "code": "return data"},
        ],
        "outputs": [
            {
                "name": "result",
                "from": "steps.transform.output",
                "value": None,
                "description": "The result",
            }
        ],
    }


class TestWorkflowsShow:
    """Tests for ploston workflows show command."""

    def test_workflows_show_existing(self, runner, mock_workflow):
        """Test showing an existing workflow."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_workflow = AsyncMock(return_value=mock_workflow)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["workflows", "show", "test-workflow"])

            assert result.exit_code == 0
            assert "test-workflow" in result.output
            assert "1.0.0" in result.output
            assert "A test workflow" in result.output
            assert "url" in result.output
            assert "fetch" in result.output
            assert "transform" in result.output

    def test_workflows_show_not_found(self, runner):
        """Test showing a non-existent workflow."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_workflow = AsyncMock(return_value=None)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["workflows", "show", "unknown"])

            assert result.exit_code == 1
            assert "not found" in result.output

    def test_workflows_show_json_output(self, runner, mock_workflow):
        """Test JSON output format."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get_workflow = AsyncMock(return_value=mock_workflow)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["--json", "workflows", "show", "test-workflow"])

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["name"] == "test-workflow"
            assert data["version"] == "1.0.0"
            assert len(data["inputs"]) == 2
            assert len(data["steps"]) == 2
            assert len(data["outputs"]) == 1


class TestWorkflowsList:
    """Tests for ploston workflows list command."""

    def test_workflows_list(self, runner, mock_workflow):
        """Test listing workflows."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_workflows = AsyncMock(return_value=[mock_workflow])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["workflows", "list"])

            assert result.exit_code == 0
            assert "test-workflow" in result.output

    def test_workflows_list_empty(self, runner):
        """Test listing empty workflows."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_workflows = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["workflows", "list"])

            assert result.exit_code == 0
            assert "0" in result.output  # "Total workflows: 0"

    def test_workflows_list_json(self, runner, mock_workflow):
        """Test JSON output for workflows list."""
        with patch("ploston_cli.main.PlostClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_workflows = AsyncMock(return_value=[mock_workflow])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = runner.invoke(cli, ["--json", "workflows", "list"])

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 1
            assert data[0]["name"] == "test-workflow"
