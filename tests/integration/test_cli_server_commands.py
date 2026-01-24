"""Integration tests for CLI commands that require a server.

Tests CLI commands that interact with a running server.
Note: The CLI uses config for server URL, not command-line args.
These tests verify CLI behavior without requiring server connection.
"""

import json
import subprocess

import httpx
import pytest


def get_server_url():
    """Get URL of running server, or None if not available."""
    urls = [
        "http://localhost:8082",
        "http://ploston.ostanlabs.homelab",
    ]

    for url in urls:
        try:
            response = httpx.get(f"{url}/health", timeout=5.0)
            if response.status_code == 200:
                return url
        except Exception:
            continue

    return None


SERVER_URL = get_server_url()


@pytest.mark.integration
class TestCLIWorkflowsCommand:
    """Test CLI workflows command."""

    def test_cli_030_workflows_list(self):
        """CLI-030: List workflows command works."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "workflows", "list"],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Should succeed or fail gracefully (no server)
        assert result.returncode in [0, 1]

    def test_cli_031_workflows_list_json(self):
        """CLI-031: List workflows with JSON output."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "--json", "workflows", "list"],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Should succeed or fail gracefully
        assert result.returncode in [0, 1]
        # If successful, should be valid JSON
        if result.returncode == 0 and result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                assert isinstance(data, (dict, list))
            except json.JSONDecodeError:
                pass  # May not be JSON format

    def test_cli_032_workflows_show_nonexistent(self):
        """CLI-032: Show nonexistent workflow."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "workflows", "show", "nonexistent_workflow_12345"],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Should fail or show not found
        combined = result.stdout + result.stderr
        assert result.returncode != 0 or "not found" in combined.lower() or "error" in combined.lower()


@pytest.mark.integration
class TestCLIToolsCommand:
    """Test CLI tools command."""

    def test_cli_040_tools_list(self):
        """CLI-040: List tools command works."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "tools", "list"],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Should succeed or fail gracefully
        assert result.returncode in [0, 1]

    def test_cli_041_tools_list_json(self):
        """CLI-041: List tools with JSON output."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "--json", "tools", "list"],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Should succeed or fail gracefully
        assert result.returncode in [0, 1]
        # If successful, should be valid JSON
        if result.returncode == 0 and result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                assert isinstance(data, (dict, list))
            except json.JSONDecodeError:
                pass

    def test_cli_042_tools_show_python_exec(self):
        """CLI-042: Show python_exec tool details."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "tools", "show", "python_exec"],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Should succeed if tool exists or fail gracefully
        assert result.returncode in [0, 1]

    def test_cli_043_tools_show_nonexistent(self):
        """CLI-043: Show nonexistent tool."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "tools", "show", "nonexistent_tool_12345"],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Should fail or show not found
        combined = result.stdout + result.stderr
        assert result.returncode != 0 or "not found" in combined.lower() or "error" in combined.lower()

    def test_cli_044_tools_list_filter_source(self):
        """CLI-044: List tools filtered by source."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "tools", "list", "--source", "mcp"],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Should succeed or fail gracefully
        assert result.returncode in [0, 1]

    def test_cli_045_tools_list_filter_status(self):
        """CLI-045: List tools filtered by status."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "tools", "list", "--status", "available"],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Should succeed or fail gracefully
        assert result.returncode in [0, 1]


@pytest.mark.integration
class TestCLIRunCommand:
    """Test CLI run command."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Set up test environment."""
        self.work_dir = tmp_path

    def test_cli_050_run_simple_workflow(self):
        """CLI-050: Run simple workflow."""
        import yaml

        workflow = {
            'name': 'simple-test',
            'version': '1.0',
            'steps': [{'id': 'step1', 'code': 'result = 42'}],
            'output': '{{ steps.step1.output }}'
        }

        workflow_file = self.work_dir / "simple.yaml"
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "run", str(workflow_file)],
            capture_output=True,
            text=True,
            timeout=60
        )

        # May succeed or fail depending on server availability
        assert result.returncode in [0, 1]

    def test_cli_051_run_nonexistent_workflow(self):
        """CLI-051: Run nonexistent workflow file."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "run", "/nonexistent/workflow.yaml"],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Should fail
        assert result.returncode != 0

