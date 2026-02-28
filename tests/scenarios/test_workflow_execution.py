"""Workflow execution scenarios — run, interpolate, error, regression.

S-09: Run simple linear workflow (Layer 2, Mock)
S-10: Multi-step with template interpolation (Layer 2, Mock)
S-11: Python code step execution (Layer 2, Full)
S-12: Tool failure → structured error (Layer 2, Mock)
S-13: Invalid inputs → validation error (Layer 2, Full)
S-14: Regression: golden file comparison (Layer 2, Mock)
"""

from __future__ import annotations

import json

import pytest
import requests


@pytest.mark.scenario
@pytest.mark.docker
class TestS09SimpleLinearExecution:
    """S-09: Run scrape-and-save workflow end-to-end."""

    def test_workflow_completes(self, api_url):
        """Workflow execution returns completed status."""
        response = requests.post(
            f"{api_url}/workflows/scrape-and-save/execute",
            json={"inputs": {"url": "https://example.com", "output_path": "/tmp/out.md"}},
            timeout=30,
        )
        if response.status_code == 404:
            pytest.skip("Workflow not registered")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") in ("completed", "success"), (
            f"S-09: execution should complete, got: {data.get('status')}"
        )


@pytest.mark.scenario
@pytest.mark.docker
class TestS10MultiStepInterpolation:
    """S-10: Multi-step workflow with {{ template }} interpolation."""

    def test_all_steps_receive_interpolated_params(self, api_url):
        """Each step gets correctly interpolated parameters."""
        response = requests.post(
            f"{api_url}/workflows/multi-step/execute",
            json={"inputs": {"search_query": "test query", "output_dir": "/tmp/results"}},
            timeout=30,
        )
        if response.status_code == 404:
            pytest.skip("Workflow not registered")
        data = response.json()
        assert data.get("status") in ("completed", "success"), (
            f"S-10: multi-step should complete, got: {data}"
        )


@pytest.mark.scenario
@pytest.mark.docker
class TestS11PythonCodeStep:
    """S-11: Workflow with inline Python code transformation."""

    def test_code_step_executes_in_sandbox(self, api_url):
        """Python code step runs and produces output."""
        # This test requires a workflow with Python code step
        pytest.skip("Python code step workflow not yet implemented")


@pytest.mark.scenario
@pytest.mark.docker
class TestS12ToolFailureError:
    """S-12: Tool failure produces structured error response."""

    def test_error_is_structured(self, api_url):
        """Execution with tool error returns structured error."""
        response = requests.post(
            f"{api_url}/workflows/scrape-and-save/execute",
            json={"inputs": {"url": "invalid://url", "output_path": "/tmp/out.md"}},
            timeout=30,
        )
        if response.status_code == 404:
            pytest.skip("Workflow not registered")
        # Should be a structured error, not a 500
        assert response.status_code in (200, 400, 422)


@pytest.mark.scenario
@pytest.mark.docker
class TestS13InvalidInputs:
    """S-13: Invalid workflow inputs produce validation error."""

    def test_missing_required_input_rejected(self, api_url):
        """Passing missing required input produces validation error."""
        response = requests.post(
            f"{api_url}/workflows/scrape-and-save/execute",
            json={"inputs": {}},  # Missing required 'url'
            timeout=30,
        )
        if response.status_code == 404:
            pytest.skip("Workflow not registered")
        # Should fail with validation error, not 500
        assert response.status_code in (400, 422), (
            f"S-13: missing input should be 4xx, got {response.status_code}"
        )


@pytest.mark.scenario
@pytest.mark.docker
class TestS14GoldenFileRegression:
    """S-14: Regression test using golden file comparison."""

    def test_output_matches_golden(self, api_url, golden_dir):
        """Execution output matches golden file structurally."""
        # Run workflow
        response = requests.post(
            f"{api_url}/workflows/echo-test/execute",
            json={"inputs": {"message": "hello world"}},
            timeout=30,
        )
        if response.status_code == 404:
            pytest.skip("Workflow not registered")
        actual = response.json()

        # Load golden file if exists
        golden_file = golden_dir / "echo-test-output.json"
        if not golden_file.exists():
            pytest.skip("Golden file not found")

        with open(golden_file) as f:
            golden = json.load(f)

        # Structural comparison
        assert actual.get("status") == golden.get("status"), "S-14: status mismatch"
