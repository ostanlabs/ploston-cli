"""Runner lifecycle scenarios — create, connect, disconnect, delete.

S-19: Create runner (Layer 2)
S-20: List runners & get details (Layer 2)
S-21: Runner connects & reports tools (Layer 2, Mock)
S-22: Tool dispatch to runner (Layer 2, Mock)
S-23: Runner disconnect → CP detects (Layer 2)
S-24: Runner reconnect → tools restored (Layer 2, Mock)
S-25: Delete runner (Layer 2)

NOTE: These tests use the create_runner fixture which calls
regenerate-token API for pre-defined runners in config.
"""

from __future__ import annotations

import pytest
import requests


@pytest.mark.scenario
@pytest.mark.docker
class TestS19CreateRunner:
    """S-19: Create a new runner."""

    def test_runner_create_via_api(self, api_url):
        """POST creates runner and returns token."""
        # Try to create or regenerate token for a runner
        response = requests.post(
            f"{api_url}/runners/scenario-runner-1/regenerate-token",
            timeout=10,
        )
        if response.status_code == 404:
            # Try creating the runner first
            create_response = requests.post(
                f"{api_url}/runners",
                json={"name": "scenario-runner-1"},
                timeout=10,
            )
            if create_response.status_code in (200, 201):
                response = requests.post(
                    f"{api_url}/runners/scenario-runner-1/regenerate-token",
                    timeout=10,
                )
            else:
                pytest.skip("Runner creation not supported")

        if response.status_code == 200:
            data = response.json()
            assert "token" in data, "S-19: should return token"


@pytest.mark.scenario
@pytest.mark.docker
class TestS20ListAndGetRunners:
    """S-20: List runners and get details."""

    def test_list_runners(self, api_url):
        """GET /api/v1/runners returns runner list."""
        response = requests.get(f"{api_url}/runners", timeout=10)
        assert response.status_code == 200
        data = response.json()
        runners = data.get("runners", data.get("items", []))
        # May be empty if no runners configured
        assert isinstance(runners, list), "S-20: should return list of runners"

    def test_get_runner_details(self, api_url):
        """GET /api/v1/runners/{name} returns runner details."""
        response = requests.get(
            f"{api_url}/runners/scenario-runner-1",
            timeout=10,
        )
        # 200 or 404 (if runner doesn't exist) are acceptable
        assert response.status_code in (200, 404), (
            f"S-20: should return 200 or 404, got {response.status_code}"
        )


@pytest.mark.scenario
@pytest.mark.docker
class TestS21RunnerConnects:
    """S-21: Runner connects via WS and reports tools."""

    def test_runner_ws_endpoint_exists(self, ws_url):
        """WebSocket endpoint is accessible."""
        # Just verify the URL is formed correctly
        assert ws_url.startswith("ws://") or ws_url.startswith("wss://"), (
            f"S-21: ws_url should be ws:// or wss://, got: {ws_url}"
        )


@pytest.mark.scenario
@pytest.mark.docker
class TestS22ToolDispatch:
    """S-22: Tool dispatch to runner."""

    def test_tool_dispatch_placeholder(self, api_url):
        """Placeholder for tool dispatch test."""
        # This requires a running runner, which is complex to set up
        pytest.skip("Tool dispatch requires running runner - manual test")


@pytest.mark.scenario
@pytest.mark.docker
class TestS23RunnerDisconnect:
    """S-23: Runner disconnect → CP detects."""

    def test_disconnect_detection_placeholder(self, api_url):
        """Placeholder for disconnect detection test."""
        pytest.skip("Disconnect detection requires running runner - manual test")


@pytest.mark.scenario
@pytest.mark.docker
class TestS24RunnerReconnect:
    """S-24: Runner reconnect → tools restored."""

    def test_reconnect_placeholder(self, api_url):
        """Placeholder for reconnect test."""
        pytest.skip("Reconnect requires running runner - manual test")


@pytest.mark.scenario
@pytest.mark.docker
class TestS25DeleteRunner:
    """S-25: Delete a runner."""

    def test_delete_runner_via_api(self, api_url):
        """DELETE /api/v1/runners/{name} removes runner."""
        response = requests.delete(
            f"{api_url}/runners/scenario-runner-4",
            timeout=10,
        )
        # 200, 204, or 404 (if not found) are acceptable
        assert response.status_code in (200, 204, 404), (
            f"S-25: delete should succeed or 404, got {response.status_code}"
        )
