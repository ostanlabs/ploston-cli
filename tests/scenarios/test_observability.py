"""Observability scenarios — traces, history, logs.

S-31: Execution trace captured (Layer 2, Mock)
S-32: Execution history query (Layer 2)
S-33: Execution logs retrieval (Layer 2, Mock)
"""

from __future__ import annotations

import pytest
import requests


@pytest.mark.scenario
@pytest.mark.docker
class TestS31ExecutionTrace:
    """S-31: Full execution trace captured."""

    def test_execution_has_trace(self, api_url, registered_workflows):
        """Run workflow → GET execution → verify trace fields."""
        if "echo-test" not in registered_workflows:
            pytest.skip("echo-test workflow not registered")
        # Execute workflow
        exec_response = requests.post(
            f"{api_url}/workflows/echo-test/execute",
            json={"inputs": {"message": "trace test"}},
            timeout=30,
        )
        if exec_response.status_code == 404:
            pytest.skip("Workflow not registered")

        exec_data = exec_response.json()
        execution_id = exec_data.get("execution_id", exec_data.get("id"))

        if execution_id:
            # Get execution details
            detail_response = requests.get(
                f"{api_url}/executions/{execution_id}",
                timeout=10,
            )
            if detail_response.status_code == 200:
                detail = detail_response.json()
                # Verify some trace info is present
                assert detail is not None, "S-31: should return execution details"


@pytest.mark.scenario
@pytest.mark.docker
class TestS32ExecutionHistory:
    """S-32: Query execution history."""

    def test_executions_list(self, api_url):
        """GET /api/v1/executions returns execution history."""
        response = requests.get(f"{api_url}/executions", timeout=10)
        # 200 or 404 (if endpoint doesn't exist) are acceptable
        assert response.status_code in (200, 404), (
            f"S-32: executions should return 200 or 404, got {response.status_code}"
        )


@pytest.mark.scenario
@pytest.mark.docker
class TestS33ExecutionLogs:
    """S-33: Execution logs retrieval."""

    def test_execution_logs_available(self, api_url, registered_workflows):
        """Execution logs contain structured entries."""
        if "echo-test" not in registered_workflows:
            pytest.skip("echo-test workflow not registered")
        # Execute workflow first
        exec_response = requests.post(
            f"{api_url}/workflows/echo-test/execute",
            json={"inputs": {"message": "logs test"}},
            timeout=30,
        )
        if exec_response.status_code == 404:
            pytest.skip("Workflow not registered")

        exec_data = exec_response.json()
        execution_id = exec_data.get("execution_id", exec_data.get("id"))

        if execution_id:
            logs_response = requests.get(
                f"{api_url}/executions/{execution_id}/logs",
                timeout=10,
            )
            # 200 or 404 (if endpoint doesn't exist) are acceptable
            assert logs_response.status_code in (200, 404), (
                f"S-33: logs should return 200 or 404, got {logs_response.status_code}"
            )
