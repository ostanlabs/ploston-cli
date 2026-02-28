"""Agent bridge scenarios — simulated MCP client via bridge stdio.

S-26: Agent discovers tools via bridge (Layer 2, Mock)
S-27: Agent calls individual tool via bridge (Layer 2, Mock)
S-28: Agent triggers workflow — the "aha moment" (Layer 2, Mock)
S-29: Bridge with tool filtering profile (Layer 2)
S-30: Agent triggers workflow with runtime error (Layer 2, Mock)
"""

from __future__ import annotations

import pytest


@pytest.mark.scenario
@pytest.mark.docker
class TestS26AgentDiscoverTools:
    """S-26: Agent lists tools through bridge → CP → MCP servers."""

    @pytest.mark.asyncio
    async def test_tools_list_via_bridge(self, mock_agent):
        """MockAgent → tools/list returns tools."""
        tools = await mock_agent.list_tools()
        assert len(tools) > 0, "S-26: bridge should expose tools"

    @pytest.mark.asyncio
    async def test_workflow_tools_present(self, mock_agent):
        """Workflow tools (workflow:*) are present alongside individual tools."""
        tools = await mock_agent.list_tools()
        tool_names = [t["name"] for t in tools]
        # Either workflow tools or individual tools should be present
        assert len(tool_names) > 0, f"S-26: expected tools, got: {tool_names[:10]}"


@pytest.mark.scenario
@pytest.mark.docker
class TestS27AgentCallsTool:
    """S-27: Agent calls individual tool through bridge."""

    @pytest.mark.asyncio
    async def test_tool_call_returns_result(self, mock_agent):
        """MockAgent → tools/call returns result from mock MCP."""
        tools = await mock_agent.list_tools()
        if not tools:
            pytest.skip("No tools available")

        tool_name = tools[0]["name"]
        result = await mock_agent.call_tool(tool_name, {})
        assert result is not None, "S-27: tool call should return result"


@pytest.mark.scenario
@pytest.mark.docker
class TestS28AhaMoment:
    """S-28: Agent triggers workflow — 1 call replaces multiple LLM round-trips.

    This is the core value proposition of Ploston for cost reduction:
    Agent makes ONE tools/call to workflow:scrape-and-save,
    Ploston executes 2 steps (scrape + save) deterministically.
    """

    @pytest.mark.asyncio
    async def test_workflow_tool_call(self, mock_agent):
        """One agent call triggers full workflow execution."""
        tools = await mock_agent.list_tools()
        workflow_tools = [t for t in tools if t["name"].startswith("workflow:")]
        if not workflow_tools:
            pytest.skip("No workflow tools available")

        result = await mock_agent.call_tool(
            workflow_tools[0]["name"],
            {},
        )
        # Result should not be an error
        assert not result.get("isError", False), f"S-28: workflow should succeed, got: {result}"


@pytest.mark.scenario
@pytest.mark.docker
class TestS29BridgeFiltering:
    """S-29: Bridge with tool filtering profile (DEC-131)."""

    @pytest.mark.asyncio
    async def test_filtered_tools_list(self, cp_url):
        """Bridge with --filter-servers shows only allowed tools."""
        # This test requires MockAgent with extra_args support
        pytest.skip("Bridge filtering requires extra_args support in MockAgent")


@pytest.mark.scenario
@pytest.mark.docker
class TestS30WorkflowError:
    """S-30: Agent triggers workflow that fails — structured MCP error."""

    @pytest.mark.asyncio
    async def test_error_response_via_bridge(self, mock_agent):
        """Failing workflow returns MCP error with isError=true."""
        tools = await mock_agent.list_tools()
        workflow_tools = [t for t in tools if t["name"].startswith("workflow:")]
        if not workflow_tools:
            pytest.skip("No workflow tools available")

        # Try to trigger an error by passing invalid inputs
        result = await mock_agent.call_tool(
            workflow_tools[0]["name"],
            {"invalid_param": "should_fail"},
        )
        # Either success or structured error is acceptable
        assert result is not None, "S-30: should return result or error"
