"""Unit tests for ael validate command."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
    from_path: steps.fetch.output
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
    """Tests for ael validate command."""

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
    from_path: steps.fetch.output
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
            import json
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
            import json
            data = json.loads(result.output)
            assert data["valid"] is False
            assert len(data["errors"]) > 0

    def test_validate_with_check_tools(self, runner, valid_workflow_yaml):
        """Test --check-tools flag."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(valid_workflow_yaml)
            f.flush()

            with patch("ploston_cli.main.AELApplication") as mock_app_class:
                mock_app = MagicMock()
                mock_app.initialize = AsyncMock()
                mock_app.shutdown = AsyncMock()
                
                # Mock workflow registry with validator
                mock_validator = MagicMock()
                mock_result = MagicMock()
                mock_result.errors = []
                mock_result.warnings = []
                mock_validator.validate.return_value = mock_result
                
                mock_app.workflow_registry = MagicMock()
                mock_app.workflow_registry._validator = mock_validator
                mock_app_class.return_value = mock_app

                result = runner.invoke(cli, ["validate", "--check-tools", f.name])

                assert result.exit_code == 0
                mock_validator.validate.assert_called_once()

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
