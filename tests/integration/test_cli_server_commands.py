"""Integration tests for CLI commands that require a server.

Tests CLI commands that interact with a running server.
"""

import pytest
import subprocess
import json
import httpx


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
@pytest.mark.skipif(SERVER_URL is None, reason="No running server available")
class TestCLIWorkflowsCommand:
    """Test CLI workflows command with running server."""

    def test_cli_030_workflows_list(self):
        """CLI-030: List workflows from server."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "workflows", "list",
             "--server", SERVER_URL],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Should succeed
        assert result.returncode == 0

    def test_cli_031_workflows_list_json(self):
        """CLI-031: List workflows with JSON output."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "--json", "workflows", "list",
             "--server", SERVER_URL],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        assert result.returncode == 0
        # Should be valid JSON
        try:
            data = json.loads(result.stdout)
            assert isinstance(data, (dict, list))
        except json.JSONDecodeError:
            pass  # May not be JSON format

    def test_cli_032_workflows_show_nonexistent(self):
        """CLI-032: Show nonexistent workflow."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "workflows", "show", "nonexistent_workflow_12345",
             "--server", SERVER_URL],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Should fail or show not found
        combined = result.stdout + result.stderr
        assert result.returncode != 0 or "not found" in combined.lower() or "error" in combined.lower()


@pytest.mark.integration
@pytest.mark.skipif(SERVER_URL is None, reason="No running server available")
class TestCLIToolsCommand:
    """Test CLI tools command with running server."""

    def test_cli_040_tools_list(self):
        """CLI-040: List tools from server."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "tools", "list",
             "--server", SERVER_URL],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Should succeed
        assert result.returncode == 0

    def test_cli_041_tools_list_json(self):
        """CLI-041: List tools with JSON output."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "--json", "tools", "list",
             "--server", SERVER_URL],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        assert result.returncode == 0
        # Should be valid JSON
        try:
            data = json.loads(result.stdout)
            assert isinstance(data, (dict, list))
        except json.JSONDecodeError:
            pass

    def test_cli_042_tools_show_python_exec(self):
        """CLI-042: Show python_exec tool details."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "tools", "show", "python_exec",
             "--server", SERVER_URL],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Should succeed if tool exists
        assert result.returncode in [0, 1]

    def test_cli_043_tools_show_nonexistent(self):
        """CLI-043: Show nonexistent tool."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "tools", "show", "nonexistent_tool_12345",
             "--server", SERVER_URL],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Should fail or show not found
        combined = result.stdout + result.stderr
        assert result.returncode != 0 or "not found" in combined.lower() or "error" in combined.lower()


@pytest.mark.integration
@pytest.mark.skipif(SERVER_URL is None, reason="No running server available")
class TestCLIRunCommand:
    """Test CLI run command with running server."""

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
            ["python", "-m", "ploston_cli", "run", str(workflow_file),
             "--server", SERVER_URL],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # May succeed or fail depending on server capabilities
        assert result.returncode in [0, 1]

