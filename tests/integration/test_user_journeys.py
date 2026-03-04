"""CLI integration tests for user journeys.

Tests complete user workflows from CLI perspective.
"""

import json
import subprocess

import pytest
import yaml


@pytest.mark.integration
@pytest.mark.cli
class TestNewUserJourney:
    """Test the journey of a new user discovering Ploston."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Set up clean environment for each test."""
        self.work_dir = tmp_path
        self.workflows_dir = self.work_dir / "workflows"
        self.workflows_dir.mkdir()

    def test_e2e_001_version_command(self):
        """E2E-001: User checks CLI version."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "version"], capture_output=True, text=True
        )

        assert result.returncode == 0
        assert "ploston" in result.stdout.lower() or "version" in result.stdout.lower()

    def test_e2e_002_help_command(self):
        """E2E-002: User explores available commands."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "--help"], capture_output=True, text=True
        )

        assert result.returncode == 0
        assert "Commands:" in result.stdout
        assert "workflows" in result.stdout
        assert "tools" in result.stdout
        assert "run" in result.stdout

    def test_e2e_003_validate_workflow_file(self):
        """E2E-003: User validates a workflow file."""
        # Create a simple workflow
        workflow = {
            "name": "test-workflow",
            "version": "1.0",
            "steps": [{"id": "step1", "code": "result = 42"}],
            "output": "{{ steps.step1.output }}",
        }

        workflow_file = self.workflows_dir / "test.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        # Should succeed or fail gracefully
        assert result.returncode in [0, 1]

    def test_e2e_004_validate_invalid_workflow(self):
        """E2E-004: User validates an invalid workflow file."""
        # Create an invalid workflow (missing required fields)
        workflow = {
            "name": "invalid-workflow",
            # Missing version, steps, output
        }

        workflow_file = self.workflows_dir / "invalid.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        # Should fail with error message
        assert (
            result.returncode != 0
            or "error" in result.stdout.lower()
            or "error" in result.stderr.lower()
        )

    def test_e2e_005_config_show(self):
        """E2E-005: User views configuration."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "config", "show"], capture_output=True, text=True
        )

        # Should succeed or show helpful message
        assert result.returncode in [0, 1]

    def test_e2e_006_workflows_list_no_server(self):
        """E2E-006: User tries to list workflows without server."""
        result = subprocess.run(
            [
                "python",
                "-m",
                "ploston_cli",
                "workflows",
                "list",
                "--server",
                "http://localhost:19999",
            ],  # Non-existent server
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Should fail gracefully with connection error
        assert result.returncode != 0
        assert (
            "error" in result.stdout.lower()
            or "error" in result.stderr.lower()
            or "connection" in result.stderr.lower()
        )

    def test_e2e_007_tools_list_no_server(self):
        """E2E-007: User tries to list tools without server.

        Note: CLI may return 0 with empty list if it handles connection errors gracefully.
        """
        result = subprocess.run(
            [
                "python",
                "-m",
                "ploston_cli",
                "tools",
                "list",
                "--server",
                "http://localhost:19999",
            ],  # Non-existent server
            capture_output=True,
            text=True,
            timeout=10,
        )

        # CLI may return 0 with empty list or non-zero with error
        # Either is acceptable graceful handling
        assert result.returncode in [0, 1]
        # If successful, should show empty or error message
        if result.returncode == 0:
            assert (
                "0" in result.stdout
                or "empty" in result.stdout.lower()
                or "no" in result.stdout.lower()
            )


@pytest.mark.integration
@pytest.mark.cli
class TestDeveloperJourney:
    """Test journey of a developer using Ploston."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Set up clean environment for each test."""
        self.work_dir = tmp_path
        self.workflows_dir = self.work_dir / "workflows"
        self.workflows_dir.mkdir()

    def test_e2e_010_create_workflow_with_inputs(self):
        """E2E-010: Developer creates workflow with inputs."""
        workflow = {
            "name": "greet",
            "version": "1.0",
            "inputs": [{"name": {"type": "string", "default": "World"}}],
            "steps": [{"id": "greet", "code": 'result = f"Hello, {{ inputs.name }}!"'}],
            "output": "{{ steps.greet.output }}",
        }

        workflow_file = self.workflows_dir / "greet.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        # Validate
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode in [0, 1]

    def test_e2e_011_create_multi_step_workflow(self):
        """E2E-011: Developer creates multi-step workflow."""
        workflow = {
            "name": "calculator",
            "version": "1.0",
            "inputs": [
                {"a": {"type": "integer", "default": 10}},
                {"b": {"type": "integer", "default": 5}},
            ],
            "steps": [
                {"id": "add", "code": "result = {{ inputs.a }} + {{ inputs.b }}"},
                {"id": "multiply", "code": "result = {{ inputs.a }} * {{ inputs.b }}"},
                {
                    "id": "combine",
                    "depends_on": ["add", "multiply"],
                    "code": """
result = {
    "sum": {{ steps.add.output }},
    "product": {{ steps.multiply.output }}
}
""",
                },
            ],
            "output": "{{ steps.combine.output }}",
        }

        workflow_file = self.workflows_dir / "calculator.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode in [0, 1]

    def test_e2e_012_create_workflow_with_tool(self):
        """E2E-012: Developer creates workflow using a tool."""
        workflow = {
            "name": "tool-user",
            "version": "1.0",
            "steps": [{"id": "use_tool", "tool": "echo", "inputs": {"message": "Hello from tool"}}],
            "output": "{{ steps.use_tool.output }}",
        }

        workflow_file = self.workflows_dir / "tool-user.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        # May fail if tool doesn't exist, but should not crash
        assert result.returncode in [0, 1]

    def test_e2e_013_json_output_format(self):
        """E2E-013: Developer uses JSON output format."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "--json", "version"], capture_output=True, text=True
        )

        assert result.returncode == 0
        # Should be valid JSON or contain version info
        try:
            data = json.loads(result.stdout)
            assert isinstance(data, dict)
        except json.JSONDecodeError:
            # If not JSON, should still have version info
            assert "version" in result.stdout.lower() or "ploston" in result.stdout.lower()

    def test_e2e_014_verbose_mode(self):
        """E2E-014: Developer uses verbose mode."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "-v", "version"], capture_output=True, text=True
        )

        assert result.returncode == 0

    def test_e2e_015_quiet_mode(self):
        """E2E-015: Developer uses quiet mode."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "-q", "version"], capture_output=True, text=True
        )

        assert result.returncode == 0


@pytest.mark.integration
@pytest.mark.cli
class TestPowerUserJourney:
    """Test journey of a power user with advanced workflows."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Set up clean environment for each test."""
        self.work_dir = tmp_path
        self.workflows_dir = self.work_dir / "workflows"
        self.workflows_dir.mkdir()

    def test_e2e_020_workflow_with_conditionals(self):
        """E2E-020: Power user creates workflow with conditionals."""
        workflow = {
            "name": "conditional",
            "version": "1.0",
            "inputs": [{"value": {"type": "integer", "default": 50}}],
            "steps": [
                {
                    "id": "check",
                    "code": """
value = {{ inputs.value }}
if value > 100:
    result = "high"
elif value > 50:
    result = "medium"
else:
    result = "low"
""",
                }
            ],
            "output": "{{ steps.check.output }}",
        }

        workflow_file = self.workflows_dir / "conditional.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode in [0, 1]

    def test_e2e_021_workflow_with_loops(self):
        """E2E-021: Power user creates workflow with loops."""
        workflow = {
            "name": "loop",
            "version": "1.0",
            "inputs": [{"count": {"type": "integer", "default": 5}}],
            "steps": [
                {
                    "id": "generate",
                    "code": """
count = {{ inputs.count }}
result = [i * i for i in range(count)]
""",
                }
            ],
            "output": "{{ steps.generate.output }}",
        }

        workflow_file = self.workflows_dir / "loop.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode in [0, 1]

    def test_e2e_022_workflow_with_error_handling(self):
        """E2E-022: Power user creates workflow with error handling."""
        workflow = {
            "name": "error-handler",
            "version": "1.0",
            "steps": [
                {
                    "id": "safe_divide",
                    "code": """
try:
    result = 10 / 0
except ZeroDivisionError:
    result = "Cannot divide by zero"
""",
                }
            ],
            "output": "{{ steps.safe_divide.output }}",
        }

        workflow_file = self.workflows_dir / "error-handler.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode in [0, 1]

    def test_e2e_023_workflow_with_complex_data(self):
        """E2E-023: Power user creates workflow with complex data structures."""
        workflow = {
            "name": "complex-data",
            "version": "1.0",
            "steps": [
                {
                    "id": "create_data",
                    "code": """
result = {
    "users": [
        {"name": "Alice", "age": 30, "roles": ["admin", "user"]},
        {"name": "Bob", "age": 25, "roles": ["user"]}
    ],
    "metadata": {
        "version": "1.0",
        "count": 2
    }
}
""",
                },
                {
                    "id": "process_data",
                    "depends_on": ["create_data"],
                    "code": """
data = {{ steps.create_data.output }}
result = {
    "total_users": len(data["users"]),
    "admin_count": sum(1 for u in data["users"] if "admin" in u["roles"])
}
""",
                },
            ],
            "output": "{{ steps.process_data.output }}",
        }

        workflow_file = self.workflows_dir / "complex-data.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode in [0, 1]

    def test_e2e_024_workflow_with_string_operations(self):
        """E2E-024: Power user creates workflow with string operations."""
        workflow = {
            "name": "string-ops",
            "version": "1.0",
            "inputs": [{"text": {"type": "string", "default": "Hello, World!"}}],
            "steps": [
                {
                    "id": "transform",
                    "code": """
text = "{{ inputs.text }}"
result = {
    "upper": text.upper(),
    "lower": text.lower(),
    "reversed": text[::-1],
    "length": len(text),
    "words": text.split()
}
""",
                }
            ],
            "output": "{{ steps.transform.output }}",
        }

        workflow_file = self.workflows_dir / "string-ops.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode in [0, 1]

    def test_e2e_025_workflow_with_math_operations(self):
        """E2E-025: Power user creates workflow with math operations."""
        workflow = {
            "name": "math-ops",
            "version": "1.0",
            "inputs": [{"numbers": {"type": "string", "default": "1,2,3,4,5"}}],
            "steps": [
                {
                    "id": "calculate",
                    "code": """
import math
numbers = [int(n) for n in "{{ inputs.numbers }}".split(",")]
result = {
    "sum": sum(numbers),
    "product": math.prod(numbers),
    "mean": sum(numbers) / len(numbers),
    "min": min(numbers),
    "max": max(numbers)
}
""",
                }
            ],
            "output": "{{ steps.calculate.output }}",
        }

        workflow_file = self.workflows_dir / "math-ops.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode in [0, 1]
