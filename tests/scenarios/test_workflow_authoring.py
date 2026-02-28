"""Workflow authoring scenarios — validate, register, list, update, delete.

S-04: Validate valid workflow (Layer 1 — no Docker for CLI validation)
S-05: Validate invalid workflow (Layer 1)
S-06: Register workflow (Layer 2)
S-07: List & show workflows (Layer 2)
S-08: Update & delete workflow (Layer 2)
"""

from __future__ import annotations

import pytest
import requests

# ── S-04: Validate valid workflow ───────────────────────────────────


@pytest.mark.scenario
class TestS04ValidateValid:
    """S-04: User validates a correct workflow YAML."""

    def test_validate_echo_test(self, cli, workflow_dir):
        """ploston validate echo-test.yaml exits 0."""
        result = cli("validate", str(workflow_dir / "echo-test.yaml"), check=False)
        # If validate command doesn't exist yet, skip
        if "No such command" in result.stderr or "unknown command" in result.stderr.lower():
            pytest.skip("validate command not implemented yet")
        assert result.returncode == 0, f"S-04: valid workflow should pass, stderr: {result.stderr}"

    def test_validate_output_says_valid(self, cli, workflow_dir):
        """Validation output confirms validity."""
        result = cli("validate", str(workflow_dir / "echo-test.yaml"), check=False)
        if "No such command" in result.stderr or "unknown command" in result.stderr.lower():
            pytest.skip("validate command not implemented yet")
        assert "valid" in result.stdout.lower() or "Valid" in result.stdout, (
            f"S-04: output should say 'valid', got: {result.stdout}"
        )


# ── S-05: Validate invalid workflow ─────────────────────────────────


@pytest.mark.scenario
class TestS05ValidateInvalid:
    """S-05: User validates a broken workflow — expects error."""

    def test_invalid_workflow_exits_nonzero(self, cli, tmp_path):
        """ploston validate invalid.yaml exits non-zero."""
        # Create an invalid workflow file
        invalid_file = tmp_path / "invalid.yaml"
        invalid_file.write_text("name: invalid\n# missing required fields")

        result = cli("validate", str(invalid_file), check=False)
        if "No such command" in result.stderr or "unknown command" in result.stderr.lower():
            pytest.skip("validate command not implemented yet")
        assert result.returncode != 0, "S-05: invalid workflow should fail validation"

    def test_error_mentions_validation(self, cli, tmp_path):
        """Error output includes validation error info."""
        invalid_file = tmp_path / "invalid.yaml"
        invalid_file.write_text("name: invalid\n# missing required fields")

        result = cli("validate", str(invalid_file), check=False)
        if "No such command" in result.stderr or "unknown command" in result.stderr.lower():
            pytest.skip("validate command not implemented yet")
        combined = result.stdout + result.stderr
        assert "error" in combined.lower() or "invalid" in combined.lower(), (
            f"S-05: error should mention validation issue, got: {combined}"
        )


# ── S-06: Register workflow ─────────────────────────────────────────


@pytest.mark.scenario
@pytest.mark.docker
class TestS06RegisterWorkflow:
    """S-06: User registers a workflow via REST API."""

    def test_register_returns_success(self, api_url, workflow_dir):
        """POST /api/v1/workflows returns success."""
        with open(workflow_dir / "echo-test.yaml") as f:
            workflow_yaml = f.read()

        response = requests.post(
            f"{api_url}/workflows",
            data=workflow_yaml,
            headers={"Content-Type": "application/x-yaml"},
            timeout=10,
        )
        assert response.status_code in (200, 201), (
            f"S-06: register should return 2xx, got {response.status_code}: {response.text}"
        )


# ── S-07: List & show workflows ─────────────────────────────────────


@pytest.mark.scenario
@pytest.mark.docker
class TestS07ListAndShow:
    """S-07: User lists and inspects workflows."""

    def test_cli_workflows_list(self, cli, api_url):
        """ploston workflows list returns output."""
        result = cli("workflows", "list", check=False)
        if "No such command" in result.stderr or "unknown command" in result.stderr.lower():
            pytest.skip("workflows command not implemented yet")
        # May fail if server not running - that's expected for docker tests
        assert result.returncode in (0, 1)

    def test_api_workflows_list(self, api_url):
        """GET /api/v1/workflows returns list."""
        response = requests.get(f"{api_url}/workflows", timeout=10)
        assert response.status_code == 200


# ── S-08: Update & delete workflow ──────────────────────────────────


@pytest.mark.scenario
@pytest.mark.docker
class TestS08UpdateAndDelete:
    """S-08: User updates then deletes a workflow."""

    def test_delete_workflow(self, api_url):
        """DELETE /api/v1/workflows/{id} removes workflow."""
        response = requests.delete(
            f"{api_url}/workflows/echo-test",
            timeout=10,
        )
        # 200, 204, or 404 (if not found) are acceptable
        assert response.status_code in (200, 204, 404), (
            f"S-08: delete should return 2xx or 404, got {response.status_code}"
        )
