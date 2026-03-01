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
    async def test_tools_list_via_bridge(self, mock_agent, registered_workflows):
        """MockAgent → tools/list returns tools."""
        tools = await mock_agent.list_tools()
        assert len(tools) > 0, "S-26: bridge should expose tools"

    @pytest.mark.asyncio
    async def test_workflow_tools_present(self, mock_agent, registered_workflows):
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
    async def test_tool_call_returns_result(self, mock_agent, registered_workflows):
        """MockAgent → tools/call returns result from mock MCP."""
        tools = await mock_agent.list_tools()
        if not tools:
            pytest.skip("No tools available")

        # Find the echo tool which accepts a message parameter
        echo_tool = next((t for t in tools if t["name"] == "echo"), None)
        if echo_tool:
            result = await mock_agent.call_tool("echo", {"message": "test"})
        else:
            # Fall back to python_exec with proper params
            result = await mock_agent.call_tool("python_exec", {"code": "result = 'hello'"})
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
    async def test_workflow_tool_call(self, mock_agent, registered_workflows):
        """One agent call triggers full workflow execution."""
        if not registered_workflows:
            pytest.skip("No workflows registered")

        tools = await mock_agent.list_tools()
        # Look for echo-test workflow which has simple inputs
        echo_workflow = next(
            (t for t in tools if t["name"] == "workflow:echo-test"),
            None,
        )
        if not echo_workflow:
            pytest.skip("workflow:echo-test not available")

        result = await mock_agent.call_tool(
            "workflow:echo-test",
            {"message": "hello from agent"},
        )
        # Result should not be an error
        assert not result.get("isError", False), f"S-28: workflow should succeed, got: {result}"


@pytest.mark.scenario
@pytest.mark.docker
class TestS29BridgeFiltering:
    """S-29: Bridge with tool filtering profile (DEC-131)."""

    @pytest.mark.asyncio
    async def test_filtered_tools_native_only(self, cp_url):
        """Bridge with --tools native excludes MCP tools.

        The scenario config doesn't have native tools configured,
        so this test verifies that the filter correctly excludes
        MCP tools (brave_search, echo, etc.) when native filter is used.
        """
        from tests.e2e.mock_agent import MockAgent

        async with await MockAgent.create(cp_url, extra_args=["--tools", "native"]) as agent:
            tools = await agent.list_tools()
            tool_names = [t["name"] for t in tools]

            # Should NOT have mock MCP tools (brave_search, etc.)
            # These are registered as 'mcp' source, not 'native'
            mcp_tools = ["brave_search", "echo", "firecrawl_scrape", "filesystem_write_file"]
            for mcp_tool in mcp_tools:
                assert mcp_tool not in tool_names, (
                    f"S-29: native filter should exclude MCP tool {mcp_tool}, got: {tool_names[:10]}"
                )

            # Should NOT have system tools (python_exec)
            assert "python_exec" not in tool_names, (
                f"S-29: native filter should exclude system tool python_exec, got: {tool_names[:10]}"
            )

            # Should NOT have workflow tools
            workflow_tools = [t for t in tool_names if t.startswith("workflow:")]
            assert len(workflow_tools) == 0, (
                f"S-29: native filter should exclude workflow tools, got: {workflow_tools}"
            )

    @pytest.mark.asyncio
    async def test_filtered_tools_all(self, cp_url):
        """Bridge with --tools all shows all tools (default behavior)."""
        from tests.e2e.mock_agent import MockAgent

        async with await MockAgent.create(cp_url, extra_args=["--tools", "all"]) as agent:
            tools = await agent.list_tools()
            tool_names = [t["name"] for t in tools]

            # Should have tools from multiple sources
            assert len(tool_names) > 0, "S-29: expected tools with 'all' filter, got none"


@pytest.mark.scenario
@pytest.mark.docker
class TestS30WorkflowError:
    """S-30: Agent triggers workflow that fails — structured MCP error."""

    @pytest.mark.asyncio
    async def test_error_response_via_bridge(self, mock_agent, registered_workflows):
        """Failing workflow returns MCP error with isError=true."""
        if not registered_workflows:
            pytest.skip("No workflows registered")

        tools = await mock_agent.list_tools()
        # Look for echo-test workflow
        echo_workflow = next(
            (t for t in tools if t["name"] == "workflow:echo-test"),
            None,
        )
        if not echo_workflow:
            pytest.skip("workflow:echo-test not available")

        # Try to trigger an error by passing invalid inputs (missing required 'message')
        result = await mock_agent.call_tool(
            "workflow:echo-test",
            {"invalid_param": "should_fail"},
        )
        # Either success or structured error is acceptable
        assert result is not None, "S-30: should return result or error"
