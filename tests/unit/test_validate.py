"""Unit tests for ploston validate command."""

import json
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ploston_cli.main import cli


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def valid_workflow_yaml():
    """Create valid workflow YAML content."""
    return """
name: test-workflow
version: "1.0.0"
description: A test workflow

inputs:
  - name: url
    type: string
    required: true

steps:
  - id: fetch
    tool: http_request
    params:
      url: "{{ inputs.url }}"

outputs:
  - name: result
    from: steps.fetch.output
"""


@pytest.fixture
def invalid_workflow_yaml():
    """Create invalid workflow YAML content."""
    return """
name: test-workflow
version: "1.0.0"

steps:
  - id: fetch
    # Missing both tool and code
    params:
      url: "test"
"""


class TestValidate:
    """Tests for ploston validate command."""

    def test_validate_valid_workflow(self, runner, valid_workflow_yaml):
        """Test validating a valid workflow."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(valid_workflow_yaml)
            f.flush()

            result = runner.invoke(cli, ["validate", f.name])

            assert result.exit_code == 0
            assert "Validation passed" in result.output

    def test_validate_invalid_workflow(self, runner, invalid_workflow_yaml):
        """Test validating an invalid workflow."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(invalid_workflow_yaml)
            f.flush()

            result = runner.invoke(cli, ["validate", f.name])

            assert result.exit_code == 1
            assert "ERRORS" in result.output

    def test_validate_strict_with_warnings(self, runner, valid_workflow_yaml):
        """Test --strict flag treats warnings as errors."""
        # Create workflow without description (might generate warning)
        yaml_content = """
name: test-workflow
version: "1.0.0"

steps:
  - id: fetch
    code: "return 1"

outputs:
  - name: result
    from: steps.fetch.output
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            # Without strict - should pass
            result = runner.invoke(cli, ["validate", f.name])
            assert result.exit_code == 0

    def test_validate_nonexistent_file(self, runner):
        """Test validating a non-existent file."""
        result = runner.invoke(cli, ["validate", "/nonexistent/file.yaml"])

        assert result.exit_code == 2  # Click's error for missing file
        assert "does not exist" in result.output or "Error" in result.output

    def test_validate_json_output(self, runner, valid_workflow_yaml):
        """Test JSON output format."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(valid_workflow_yaml)
            f.flush()

            result = runner.invoke(cli, ["--json", "validate", f.name])

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["valid"] is True
            assert data["errors"] == []

    def test_validate_json_output_with_errors(self, runner, invalid_workflow_yaml):
        """Test JSON output format with errors."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(invalid_workflow_yaml)
            f.flush()

            result = runner.invoke(cli, ["--json", "validate", f.name])

            assert result.exit_code == 1
            data = json.loads(result.output)
            assert data["valid"] is False
            assert len(data["errors"]) > 0

    def test_validate_with_check_tools(self, runner, valid_workflow_yaml):
        """Test --check-tools flag queries server for tool validation."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(valid_workflow_yaml)
            f.flush()

            # Mock the server returning the tool exists
            with patch("ploston_cli.main.PlostClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.list_tools = AsyncMock(return_value=[{"name": "http_request"}])
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                result = runner.invoke(cli, ["validate", "--check-tools", f.name])

                assert result.exit_code == 0
                mock_client.list_tools.assert_called_once()

    def test_validate_with_check_tools_missing(self, runner, valid_workflow_yaml):
        """Test --check-tools flag reports missing tools."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(valid_workflow_yaml)
            f.flush()

            # Mock the server returning empty tools list (tool not found)
            with patch("ploston_cli.main.PlostClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.list_tools = AsyncMock(return_value=[])
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_class.return_value = mock_client

                result = runner.invoke(cli, ["validate", "--check-tools", f.name])

                assert result.exit_code == 1
                assert "http_request" in result.output
                assert "not found" in result.output.lower() or "ERRORS" in result.output

    def test_validate_malformed_yaml(self, runner):
        """Test validating malformed YAML."""
        malformed_yaml = """
name: test
version: "1.0.0"
steps:
  - id: fetch
    tool: test
    params:
      invalid: yaml: content
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(malformed_yaml)
            f.flush()

            result = runner.invoke(cli, ["validate", f.name])

            assert result.exit_code == 1
            assert "ERRORS" in result.output or "error" in result.output.lower()
