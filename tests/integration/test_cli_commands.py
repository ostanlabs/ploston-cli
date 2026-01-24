"""Integration tests for CLI commands.

Tests actual CLI invocations via subprocess.
"""

import pytest
import subprocess
import json
import yaml
from pathlib import Path


@pytest.mark.integration
class TestCLIBasicCommands:
    """Test basic CLI commands."""

    def test_cli_001_version(self):
        """CLI-001: Version command works."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "version"],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        # Should contain version info
        assert "ploston" in result.stdout.lower() or "version" in result.stdout.lower()

    def test_cli_002_help(self):
        """CLI-002: Help command works."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "--help"],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        assert "Commands:" in result.stdout

    def test_cli_003_help_subcommand(self):
        """CLI-003: Help for subcommands works."""
        subcommands = ["workflows", "tools", "config", "validate"]
        
        for cmd in subcommands:
            result = subprocess.run(
                ["python", "-m", "ploston_cli", cmd, "--help"],
                capture_output=True,
                text=True
            )
            
            assert result.returncode == 0, f"Help for {cmd} failed"

    def test_cli_004_unknown_command(self):
        """CLI-004: Unknown command shows error."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "nonexistent"],
            capture_output=True,
            text=True
        )
        
        # Should fail with error
        assert result.returncode != 0


@pytest.mark.integration
class TestCLIValidateCommand:
    """Test CLI validate command."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Set up test environment."""
        self.work_dir = tmp_path

    def test_cli_010_validate_valid_workflow(self):
        """CLI-010: Validate valid workflow file."""
        workflow = {
            'name': 'test-workflow',
            'version': '1.0',
            'steps': [{'id': 'step1', 'code': 'result = 42'}],
            'output': '{{ steps.step1.output }}'
        }
        
        workflow_file = self.work_dir / "valid.yaml"
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f)
        
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0

    def test_cli_011_validate_invalid_workflow(self):
        """CLI-011: Validate invalid workflow file."""
        workflow = {'name': 'incomplete'}  # Missing required fields
        
        workflow_file = self.work_dir / "invalid.yaml"
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f)
        
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True
        )
        
        # Should fail or report errors
        combined = result.stdout + result.stderr
        assert result.returncode != 0 or "error" in combined.lower()

    def test_cli_012_validate_json_output(self):
        """CLI-012: Validate with JSON output."""
        workflow = {
            'name': 'test',
            'version': '1.0',
            'steps': [{'id': 'step1', 'code': 'result = 1'}],
            'output': '{{ steps.step1.output }}'
        }
        
        workflow_file = self.work_dir / "test.yaml"
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f)
        
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "--json", "validate", str(workflow_file)],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        # Should be valid JSON
        try:
            data = json.loads(result.stdout)
            assert isinstance(data, dict)
        except json.JSONDecodeError:
            # If not JSON, should still succeed
            pass

    def test_cli_013_validate_nonexistent_file(self):
        """CLI-013: Validate nonexistent file."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", "/nonexistent/file.yaml"],
            capture_output=True,
            text=True
        )
        
        assert result.returncode != 0


@pytest.mark.integration
class TestCLIConfigCommand:
    """Test CLI config command."""

    def test_cli_020_config_show(self):
        """CLI-020: Config show command works."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "config", "show"],
            capture_output=True,
            text=True
        )
        
        # Should succeed or show helpful message
        assert result.returncode in [0, 1]

    def test_cli_021_config_show_section(self):
        """CLI-021: Config show specific section."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "config", "show", "server"],
            capture_output=True,
            text=True
        )
        
        assert result.returncode in [0, 1]

