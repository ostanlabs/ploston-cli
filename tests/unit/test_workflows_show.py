"""Unit tests for ael workflows show command."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ploston_cli.main import cli


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_workflow():
    """Create a mock workflow definition."""
    workflow = MagicMock()
    workflow.name = "test-workflow"
    workflow.version = "1.0.0"
    workflow.description = "A test workflow"

    # Mock inputs
    input1 = MagicMock()
    input1.name = "url"
    input1.type = "string"
    input1.required = True
    input1.default = None
    input1.description = "URL to process"

    input2 = MagicMock()
    input2.name = "timeout"
    input2.type = "integer"
    input2.required = False
    input2.default = 30
    input2.description = "Timeout in seconds"

    workflow.inputs = [input1, input2]

    # Mock steps
    step1 = MagicMock()
    step1.id = "fetch"
    step1.tool = "http_request"
    step1.code = None

    step2 = MagicMock()
    step2.id = "transform"
    step2.tool = None
    step2.code = "return data"

    workflow.steps = [step1, step2]

    # Mock outputs
    output1 = MagicMock()
    output1.name = "result"
    output1.from_path = "steps.transform.output"
    output1.value = None
    output1.description = "The result"

    workflow.outputs = [output1]

    return workflow


class TestWorkflowsShow:
    """Tests for ael workflows show command."""

    def test_workflows_show_existing(self, runner, mock_workflow):
        """Test showing an existing workflow."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.workflow_registry = MagicMock()
            mock_app.workflow_registry.get.return_value = mock_workflow
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["workflows", "show", "test-workflow"])

            assert result.exit_code == 0
            assert "test-workflow" in result.output
            assert "1.0.0" in result.output
            assert "A test workflow" in result.output
            assert "url" in result.output
            assert "fetch" in result.output
            assert "transform" in result.output

    def test_workflows_show_not_found_with_suggestions(self, runner, mock_workflow):
        """Test showing a non-existent workflow with suggestions."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.workflow_registry = MagicMock()
            mock_app.workflow_registry.get.return_value = None
            mock_app.workflow_registry.list_workflows.return_value = [mock_workflow]
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["workflows", "show", "test"])

            assert result.exit_code == 1
            assert "not found" in result.output
            assert "Available workflows" in result.output
            assert "test-workflow" in result.output

    def test_workflows_show_not_found_no_suggestions(self, runner):
        """Test showing a non-existent workflow without suggestions."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.workflow_registry = MagicMock()
            mock_app.workflow_registry.get.return_value = None
            mock_app.workflow_registry.list_workflows.return_value = []
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["workflows", "show", "unknown"])

            assert result.exit_code == 1
            assert "not found" in result.output
            assert "Available workflows" not in result.output

    def test_workflows_show_json_output(self, runner, mock_workflow):
        """Test JSON output format."""
        with patch("ploston_cli.main.AELApplication") as mock_app_class:
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.workflow_registry = MagicMock()
            mock_app.workflow_registry.get.return_value = mock_workflow
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["--json", "workflows", "show", "test-workflow"])

            assert result.exit_code == 0
            import json

            data = json.loads(result.output)
            assert data["name"] == "test-workflow"
            assert data["version"] == "1.0.0"
            assert len(data["inputs"]) == 2
            assert len(data["steps"]) == 2
            assert len(data["outputs"]) == 1
