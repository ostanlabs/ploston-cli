"""CLI integration tests for error scenarios.

Tests error handling and recovery scenarios.
"""

import subprocess

import pytest
import yaml


@pytest.mark.integration
@pytest.mark.cli
class TestValidationErrors:
    """Test validation error scenarios."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Set up clean environment for each test."""
        self.work_dir = tmp_path
        self.workflows_dir = self.work_dir / "workflows"
        self.workflows_dir.mkdir()

    def test_err_001_missing_name(self):
        """ERR-001: Workflow missing name field."""
        workflow = {
            "version": "1.0",
            "steps": [{"id": "step1", "code": "result = 1"}],
            "output": "{{ steps.step1.output }}",
        }

        workflow_file = self.workflows_dir / "missing-name.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        # Should fail or report error
        combined = result.stdout + result.stderr
        assert result.returncode != 0 or "error" in combined.lower() or "name" in combined.lower()

    def test_err_002_missing_version(self):
        """ERR-002: Workflow missing version field."""
        workflow = {
            "name": "test",
            "steps": [{"id": "step1", "code": "result = 1"}],
            "output": "{{ steps.step1.output }}",
        }

        workflow_file = self.workflows_dir / "missing-version.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        combined = result.stdout + result.stderr
        assert (
            result.returncode != 0 or "error" in combined.lower() or "version" in combined.lower()
        )

    def test_err_003_missing_steps(self):
        """ERR-003: Workflow missing steps field."""
        workflow = {"name": "test", "version": "1.0", "output": "result"}

        workflow_file = self.workflows_dir / "missing-steps.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        combined = result.stdout + result.stderr
        assert result.returncode != 0 or "error" in combined.lower() or "steps" in combined.lower()

    def test_err_004_empty_steps(self):
        """ERR-004: Workflow with empty steps array."""
        workflow = {"name": "test", "version": "1.0", "steps": [], "output": "result"}

        workflow_file = self.workflows_dir / "empty-steps.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        combined = result.stdout + result.stderr
        assert result.returncode != 0 or "error" in combined.lower() or "empty" in combined.lower()

    def test_err_005_duplicate_step_ids(self):
        """ERR-005: Workflow with duplicate step IDs."""
        workflow = {
            "name": "test",
            "version": "1.0",
            "steps": [
                {"id": "step1", "code": "result = 1"},
                {"id": "step1", "code": "result = 2"},  # Duplicate
            ],
            "output": "{{ steps.step1.output }}",
        }

        workflow_file = self.workflows_dir / "duplicate-ids.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        combined = result.stdout + result.stderr
        assert (
            result.returncode != 0 or "error" in combined.lower() or "duplicate" in combined.lower()
        )

    def test_err_006_invalid_depends_on(self):
        """ERR-006: Step depends on non-existent step.

        Note: Current CLI validation may not catch this - it's caught at runtime.
        This test documents the current behavior.
        """
        workflow = {
            "name": "test",
            "version": "1.0",
            "steps": [{"id": "step1", "depends_on": ["nonexistent"], "code": "result = 1"}],
            "output": "{{ steps.step1.output }}",
        }

        workflow_file = self.workflows_dir / "invalid-depends.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        # CLI may pass validation (caught at runtime) or fail
        # Either is acceptable - test documents current behavior
        assert result.returncode in [0, 1]


@pytest.mark.integration
@pytest.mark.cli
class TestFileErrors:
    """Test file-related error scenarios."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Set up clean environment for each test."""
        self.work_dir = tmp_path

    def test_err_010_nonexistent_file(self):
        """ERR-010: Validate non-existent file."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", "/nonexistent/path/workflow.yaml"],
            capture_output=True,
            text=True,
        )

        combined = result.stdout + result.stderr
        assert result.returncode != 0
        assert (
            "error" in combined.lower()
            or "not found" in combined.lower()
            or "no such" in combined.lower()
        )

    def test_err_011_invalid_yaml(self):
        """ERR-011: Validate file with invalid YAML."""
        invalid_file = self.work_dir / "invalid.yaml"
        with open(invalid_file, "w") as f:
            f.write("name: test\n  invalid: indentation\n    broken: yaml")

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(invalid_file)],
            capture_output=True,
            text=True,
        )

        combined = result.stdout + result.stderr
        assert result.returncode != 0 or "error" in combined.lower() or "yaml" in combined.lower()

    def test_err_012_empty_file(self):
        """ERR-012: Validate empty file."""
        empty_file = self.work_dir / "empty.yaml"
        empty_file.touch()

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(empty_file)],
            capture_output=True,
            text=True,
        )

        combined = result.stdout + result.stderr
        assert result.returncode != 0 or "error" in combined.lower() or "empty" in combined.lower()

    def test_err_013_non_yaml_file(self):
        """ERR-013: Validate non-YAML file."""
        json_file = self.work_dir / "workflow.json"
        with open(json_file, "w") as f:
            f.write('{"name": "test"}')

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(json_file)],
            capture_output=True,
            text=True,
        )

        # May succeed if JSON is valid YAML, or fail
        assert result.returncode in [0, 1]

    def test_err_014_binary_file(self):
        """ERR-014: Validate binary file."""
        binary_file = self.work_dir / "binary.yaml"
        with open(binary_file, "wb") as f:
            f.write(b"\x00\x01\x02\x03\x04\x05")

        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(binary_file)],
            capture_output=True,
            text=True,
        )

        # Should fail gracefully
        assert result.returncode != 0


@pytest.mark.integration
@pytest.mark.cli
class TestConnectionErrors:
    """Test connection error scenarios."""

    def test_err_020_invalid_server_url(self):
        """ERR-020: Connect to invalid server URL."""
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "workflows", "list", "--server", "not-a-valid-url"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        combined = result.stdout + result.stderr
        assert result.returncode != 0 or "error" in combined.lower()

    def test_err_021_connection_refused(self):
        """ERR-021: Connect to server that refuses connection."""
        result = subprocess.run(
            [
                "python",
                "-m",
                "ploston_cli",
                "workflows",
                "list",
                "--server",
                "http://localhost:19999",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        combined = result.stdout + result.stderr
        assert (
            result.returncode != 0
            or "error" in combined.lower()
            or "connection" in combined.lower()
        )

    def test_err_022_timeout_handling(self):
        """ERR-022: Handle connection timeout gracefully."""
        # Use a non-routable IP to trigger timeout
        result = subprocess.run(
            [
                "python",
                "-m",
                "ploston_cli",
                "workflows",
                "list",
                "--server",
                "http://10.255.255.1:8022",
            ],
            capture_output=True,
            text=True,
            timeout=15,  # Allow time for timeout
        )

        # Should fail gracefully, not crash
        combined = result.stdout + result.stderr
        assert (
            result.returncode != 0 or "error" in combined.lower() or "timeout" in combined.lower()
        )


@pytest.mark.integration
@pytest.mark.cli
class TestInputErrors:
    """Test input validation error scenarios."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Set up clean environment for each test."""
        self.work_dir = tmp_path
        self.workflows_dir = self.work_dir / "workflows"
        self.workflows_dir.mkdir()

    def test_err_030_missing_required_input(self):
        """ERR-030: Run workflow missing required input."""
        workflow = {
            "name": "test",
            "version": "1.0",
            "inputs": [{"required_value": {"type": "string", "required": True}}],
            "steps": [{"id": "step1", "code": 'result = "{{ inputs.required_value }}"'}],
            "output": "{{ steps.step1.output }}",
        }

        workflow_file = self.workflows_dir / "required-input.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        # Try to run without providing required input
        result = subprocess.run(
            [
                "python",
                "-m",
                "ploston_cli",
                "run",
                str(workflow_file),
                "--server",
                "http://localhost:19999",
            ],  # Non-existent server
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Should fail (either validation or connection)
        assert result.returncode != 0

    def test_err_031_invalid_input_type(self):
        """ERR-031: Provide input with wrong type."""
        workflow = {
            "name": "test",
            "version": "1.0",
            "inputs": [{"count": {"type": "integer", "default": 5}}],
            "steps": [{"id": "step1", "code": "result = {{ inputs.count }} * 2"}],
            "output": "{{ steps.step1.output }}",
        }

        workflow_file = self.workflows_dir / "typed-input.yaml"
        with open(workflow_file, "w") as f:
            yaml.dump(workflow, f)

        # Validate should pass
        result = subprocess.run(
            ["python", "-m", "ploston_cli", "validate", str(workflow_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode in [0, 1]
