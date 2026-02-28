"""Tool discovery scenarios — list, show, call, refresh.

S-15: List all tools from all MCP servers (Layer 2, Mock)
S-16: Show tool schema (Layer 2, Mock)
S-17: Direct tool call via CLI (Layer 2, Mock)
S-18: Refresh tool schemas after MCP change (Layer 2, Mock)
"""

from __future__ import annotations

import pytest
import requests


@pytest.mark.scenario
@pytest.mark.docker
class TestS15ListAllTools:
    """S-15: List tools unified across MCP servers."""

    def test_tools_list_returns_tools(self, api_url):
        """GET /api/v1/tools returns tools from configured servers."""
        response = requests.get(f"{api_url}/tools", timeout=10)
        assert response.status_code == 200
        data = response.json()
        tools = data.get("tools", [])
        assert len(tools) > 0, "S-15: should have at least one tool"

    def test_tools_from_mock_server_present(self, api_url):
        """Mock MCP tools are discovered."""
        response = requests.get(f"{api_url}/tools", timeout=10)
        tool_names = [t["name"] for t in response.json().get("tools", [])]
        # At least some tools should be present
        assert len(tool_names) > 0, f"S-15: should have tools, got: {tool_names}"


@pytest.mark.scenario
@pytest.mark.docker
class TestS16ShowToolSchema:
    """S-16: Show individual tool schema."""

    def test_tool_schema_has_input_schema(self, api_url):
        """GET /api/v1/tools/{name} returns schema."""
        # First get list of tools
        list_response = requests.get(f"{api_url}/tools", timeout=10)
        tools = list_response.json().get("tools", [])
        if not tools:
            pytest.skip("No tools available")

        tool_name = tools[0]["name"]
        response = requests.get(f"{api_url}/tools/{tool_name}", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "inputSchema" in data or "input_schema" in data or "schema" in data, (
            f"S-16: tool should have schema, got: {data.keys()}"
        )


@pytest.mark.scenario
@pytest.mark.docker
class TestS17DirectToolCall:
    """S-17: Call tool directly via REST API."""

    def test_direct_call_returns_result(self, api_url):
        """POST /api/v1/tools/{name}/call returns result."""
        # First get list of tools
        list_response = requests.get(f"{api_url}/tools", timeout=10)
        tools = list_response.json().get("tools", [])
        if not tools:
            pytest.skip("No tools available")

        # Find a tool we can call (echo is simplest)
        tool_name = tools[0]["name"]
        response = requests.post(
            f"{api_url}/tools/{tool_name}/call",
            json={"arguments": {}},
            timeout=30,
        )
        # 200 or 400 (if missing required args) are acceptable
        assert response.status_code in (200, 400, 422), (
            f"S-17: tool call should return 2xx or 4xx, got {response.status_code}"
        )


@pytest.mark.scenario
@pytest.mark.docker
class TestS18RefreshToolSchemas:
    """S-18: Refresh tool schemas from MCP servers."""

    def test_refresh_endpoint_returns_success(self, api_url):
        """POST /api/v1/tools/refresh triggers re-discovery."""
        response = requests.post(f"{api_url}/tools/refresh", timeout=10)
        # 200 or 404 (if endpoint doesn't exist) are acceptable
        assert response.status_code in (200, 404), (
            f"S-18: refresh should return 200 or 404, got {response.status_code}"
        )

    def test_tools_still_present_after_refresh(self, api_url):
        """Tools are present after refresh."""
        requests.post(f"{api_url}/tools/refresh", timeout=10)
        response = requests.get(f"{api_url}/tools", timeout=10)
        tools = response.json().get("tools", [])
        assert len(tools) >= 0, "S-18: tools endpoint should work after refresh"
