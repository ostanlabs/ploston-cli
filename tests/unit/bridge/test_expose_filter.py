"""Unit tests for bridge --expose filtering logic.

Tests for _filter_by_expose, _strip_prefix, _build_session_map,
tools/call reverse resolution, session map lifecycle, and --expose workflows.
"""

import logging
from unittest.mock import AsyncMock

import pytest

from ploston_cli.bridge.errors import ExposeAmbiguityError
from ploston_cli.bridge.proxy import BridgeProxy
from ploston_cli.bridge.server import BridgeServer

pytestmark = [pytest.mark.bridge, pytest.mark.bridge_unit]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tools_with_runner():
    """Assembled list: runner tools, native, CP-direct MCP, and workflow tools."""
    return [
        {"name": "mac__filesystem__read_file", "description": "Read a file", "inputSchema": {}},
        {"name": "mac__filesystem__write_file", "description": "Write a file", "inputSchema": {}},
        {"name": "mac__github__create_pr", "description": "Create PR", "inputSchema": {}},
        {"name": "python_exec", "description": "Execute Python", "inputSchema": {}},
        {"name": "slack_post", "description": "Post to Slack", "inputSchema": {}},
        {"name": "workflow_deploy_pipeline", "description": "Deploy pipeline", "inputSchema": {}},
        {"name": "workflow_schema", "description": "Get workflow YAML schema", "inputSchema": {}},
        {"name": "workflow_list", "description": "List workflows", "inputSchema": {}},
    ]


@pytest.fixture
def tools_two_runners():
    """Same mcp server on two runners — triggers ambiguity error."""
    return [
        {"name": "mac__filesystem__read_file", "description": "Read a file", "inputSchema": {}},
        {
            "name": "build-server__filesystem__read_file",
            "description": "Read a file",
            "inputSchema": {},
        },
        {"name": "python_exec", "description": "Execute Python", "inputSchema": {}},
    ]


@pytest.fixture
def mock_proxy():
    return AsyncMock(spec=BridgeProxy)


def make_server(mock_proxy, expose=None, runner=None, tools_filter="all"):
    return BridgeServer(proxy=mock_proxy, tools_filter=tools_filter, expose=expose, runner=runner)


# =============================================================================
# _filter_by_expose tests
# =============================================================================


class TestFilterByExpose:
    """Tests for _filter_by_expose method."""

    def test_matches_mcp_segment(self, mock_proxy, tools_with_runner):
        server = make_server(mock_proxy, expose="filesystem", runner="mac")
        result = server._filter_by_expose(tools_with_runner, "filesystem", "mac")
        assert len(result) == 2
        assert all("filesystem" in t["name"] for t in result)

    def test_matches_different_server(self, mock_proxy, tools_with_runner):
        server = make_server(mock_proxy, expose="github", runner="mac")
        result = server._filter_by_expose(tools_with_runner, "github", "mac")
        assert len(result) == 1
        assert result[0]["name"] == "mac__github__create_pr"

    def test_runner_name_filter(self, mock_proxy, tools_two_runners):
        server = make_server(mock_proxy, expose="filesystem", runner="mac")
        result = server._filter_by_expose(tools_two_runners, "filesystem", "mac")
        assert len(result) == 1
        assert result[0]["name"] == "mac__filesystem__read_file"

    def test_ambiguous_runner_raises_error(self, mock_proxy, tools_two_runners):
        server = make_server(mock_proxy, expose="filesystem")
        with pytest.raises(ExposeAmbiguityError) as exc_info:
            server._filter_by_expose(tools_two_runners, "filesystem", None)
        assert "build-server" in str(exc_info.value.message)
        assert "mac" in str(exc_info.value.message)

    def test_single_runner_inference_with_warning(self, mock_proxy, tools_with_runner, caplog):
        server = make_server(mock_proxy, expose="filesystem")
        with caplog.at_level(logging.WARNING):
            result = server._filter_by_expose(tools_with_runner, "filesystem", None)
        assert len(result) == 2
        assert "inferred runner" in caplog.text.lower() or "--runner not specified" in caplog.text

    def test_unknown_server_returns_empty(self, mock_proxy, tools_with_runner):
        server = make_server(mock_proxy, expose="nonexistent")
        result = server._filter_by_expose(tools_with_runner, "nonexistent", None)
        assert result == []

    def test_three_part_prefix_parsed_correctly(self, mock_proxy):
        tools = [{"name": "my-runner__my-server__my_tool", "description": "...", "inputSchema": {}}]
        server = make_server(mock_proxy, expose="my-server", runner="my-runner")
        result = server._filter_by_expose(tools, "my-server", "my-runner")
        assert len(result) == 1

    def test_non_runner_tools_excluded(self, mock_proxy, tools_with_runner):
        """Native, CP-direct MCP, and workflow tools are never matched."""
        server = make_server(mock_proxy, expose="python_exec")
        result = server._filter_by_expose(tools_with_runner, "python_exec", None)
        assert result == []


# =============================================================================
# _strip_prefix tests
# =============================================================================


class TestStripPrefix:
    """Tests for _strip_prefix method."""

    def test_strips_runner_prefix(self, mock_proxy):
        server = make_server(mock_proxy)
        tool = {"name": "mac__filesystem__read_file", "description": "Read", "inputSchema": {}}
        result = server._strip_prefix(tool)
        assert result["name"] == "read_file"
        assert result["description"] == "Read"

    def test_preserves_non_runner_tool(self, mock_proxy):
        server = make_server(mock_proxy)
        tool = {"name": "python_exec", "description": "Exec", "inputSchema": {}}
        result = server._strip_prefix(tool)
        assert result["name"] == "python_exec"

    def test_preserves_workflow_tool(self, mock_proxy):
        server = make_server(mock_proxy)
        tool = {"name": "workflow_deploy", "description": "Deploy", "inputSchema": {}}
        result = server._strip_prefix(tool)
        assert result["name"] == "workflow_deploy"

    def test_preserves_schema(self, mock_proxy):
        server = make_server(mock_proxy)
        schema = {"type": "object", "properties": {"path": {"type": "string"}}}
        tool = {"name": "mac__fs__read", "description": "Read", "inputSchema": schema}
        result = server._strip_prefix(tool)
        assert result["name"] == "read"
        assert result["inputSchema"] == schema


# =============================================================================
# _build_session_map tests
# =============================================================================


class TestBuildSessionMap:
    """Tests for _build_session_map method."""

    def test_builds_map_from_runner_tools(self, mock_proxy):
        server = make_server(mock_proxy)
        tools = [
            {"name": "mac__filesystem__read_file", "description": "...", "inputSchema": {}},
            {"name": "mac__filesystem__write_file", "description": "...", "inputSchema": {}},
        ]
        result = server._build_session_map(tools)
        assert result == {
            "read_file": "mac__filesystem__read_file",
            "write_file": "mac__filesystem__write_file",
        }

    def test_non_runner_tools_excluded_from_map(self, mock_proxy):
        server = make_server(mock_proxy)
        tools = [
            {"name": "python_exec", "description": "...", "inputSchema": {}},
            {"name": "workflow_deploy", "description": "...", "inputSchema": {}},
        ]
        result = server._build_session_map(tools)
        assert result == {}

    def test_empty_list_produces_empty_map(self, mock_proxy):
        server = make_server(mock_proxy)
        result = server._build_session_map([])
        assert result == {}

    def test_map_keys_are_clean_tool_names(self, mock_proxy):
        server = make_server(mock_proxy)
        tools = [{"name": "runner1__server1__my_tool", "description": "...", "inputSchema": {}}]
        result = server._build_session_map(tools)
        assert "my_tool" in result
        assert result["my_tool"] == "runner1__server1__my_tool"


# =============================================================================
# tools/call reverse resolution tests
# =============================================================================


class TestToolsCallReverseResolution:
    """Tests for tools/call reverse resolution via session map."""

    @pytest.mark.asyncio
    async def test_clean_name_resolved_to_canonical(self, mock_proxy):
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "OK"}]},
        }
        server = make_server(mock_proxy, expose="filesystem")
        server._session_map = {"read_file": "mac__filesystem__read_file"}

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"path": "/tmp/test"}},
        }
        response = await server.handle_request(request)

        # Verify the forwarded request used canonical name
        call_args = mock_proxy.send_request.call_args[0][0]
        assert call_args["params"]["name"] == "mac__filesystem__read_file"
        assert "result" in response

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, mock_proxy):
        server = make_server(mock_proxy, expose="filesystem")
        server._session_map = {"read_file": "mac__filesystem__read_file"}

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "unknown_tool", "arguments": {}},
        }
        response = await server.handle_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32600
        assert "not available" in response["error"]["message"]

    @pytest.mark.asyncio
    async def test_workflow_tool_called_directly(self, mock_proxy):
        """When --expose workflows, tools/call forwards unchanged."""
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "Workflow done"}]},
        }
        server = make_server(mock_proxy, expose="workflows")

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "workflow_deploy_pipeline", "arguments": {}},
        }
        await server.handle_request(request)

        call_args = mock_proxy.send_request.call_args[0][0]
        assert call_args["params"]["name"] == "workflow_deploy_pipeline"

    @pytest.mark.asyncio
    async def test_no_expose_forwards_directly(self, mock_proxy):
        """Without --expose, tools/call forwards unchanged."""
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "OK"}]},
        }
        server = make_server(mock_proxy)

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "mac__filesystem__read_file", "arguments": {}},
        }
        await server.handle_request(request)

        call_args = mock_proxy.send_request.call_args[0][0]
        assert call_args["params"]["name"] == "mac__filesystem__read_file"

    @pytest.mark.asyncio
    async def test_native_tool_no_map_lookup_without_expose(self, mock_proxy):
        """Native tools called directly when no --expose."""
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "OK"}]},
        }
        server = make_server(mock_proxy)

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "python_exec", "arguments": {}},
        }
        await server.handle_request(request)

        call_args = mock_proxy.send_request.call_args[0][0]
        assert call_args["params"]["name"] == "python_exec"

    @pytest.mark.asyncio
    async def test_expose_error_preserves_request_id(self, mock_proxy):
        server = make_server(mock_proxy, expose="filesystem")
        server._session_map = {}

        request = {
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {"name": "bad_tool", "arguments": {}},
        }
        response = await server.handle_request(request)

        assert response["id"] == 42
        assert "error" in response


# =============================================================================
# Session map lifecycle tests
# =============================================================================


class TestSessionMapLifecycle:
    """Tests for session map lifecycle."""

    @pytest.mark.asyncio
    async def test_map_built_on_tools_list(self, mock_proxy, tools_with_runner):
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": tools_with_runner},
        }
        server = make_server(mock_proxy, expose="filesystem", runner="mac")
        assert server._session_map == {}

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        await server.handle_request(request)

        assert "read_file" in server._session_map
        assert server._session_map["read_file"] == "mac__filesystem__read_file"

    @pytest.mark.asyncio
    async def test_map_rebuilt_on_subsequent_tools_list(self, mock_proxy):
        # First call: filesystem tools
        tools_v1 = [
            {"name": "mac__filesystem__read_file", "description": "...", "inputSchema": {}},
        ]
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": tools_v1},
        }
        server = make_server(mock_proxy, expose="filesystem", runner="mac")

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        await server.handle_request(request)
        assert "read_file" in server._session_map

        # Second call: different tools (runner reconnected with new tools)
        tools_v2 = [
            {"name": "mac__filesystem__list_dir", "description": "...", "inputSchema": {}},
        ]
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": tools_v2},
        }
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        await server.handle_request(request)

        assert "list_dir" in server._session_map
        assert "read_file" not in server._session_map

    def test_map_empty_on_init(self, mock_proxy):
        server = make_server(mock_proxy, expose="filesystem")
        assert server._session_map == {}


# =============================================================================
# --expose workflows tests
# =============================================================================


class TestExposeWorkflows:
    """Tests for --expose workflows tag-based filtering.

    After S-243, --expose workflows resolves to tags=["kind:workflow"]
    and delegates filtering to the CP.  The bridge returns CP response as-is.
    """

    @pytest.mark.asyncio
    async def test_tags_forwarded_to_cp(self, mock_proxy, tools_with_runner):
        """Bridge forwards tags=["kind:workflow"] when --expose workflows."""
        # Mock: CP returns only the matching tools (as it would in production)
        workflow_tools = [t for t in tools_with_runner if t["name"].startswith("workflow_")]
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": workflow_tools},
        }
        server = make_server(mock_proxy, expose="workflows")

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = await server.handle_request(request)

        # Verify tags were forwarded
        call_args = mock_proxy.send_request.call_args[0][0]
        assert call_args["params"]["tags"] == ["kind:workflow"]

        # Verify response returned as-is from CP
        tools = response["result"]["tools"]
        assert len(tools) == 3
        tool_names = [t["name"] for t in tools]
        assert "workflow_deploy_pipeline" in tool_names
        assert "workflow_schema" in tool_names
        assert "workflow_list" in tool_names

    @pytest.mark.asyncio
    async def test_no_stripping_applied(self, mock_proxy, tools_with_runner):
        """Workflow tool names are not stripped (no prefix to strip)."""
        workflow_tools = [t for t in tools_with_runner if t["name"].startswith("workflow_")]
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": workflow_tools},
        }
        server = make_server(mock_proxy, expose="workflows")

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = await server.handle_request(request)

        tool_names = [t["name"] for t in response["result"]["tools"]]
        assert "workflow_deploy_pipeline" in tool_names
        assert "workflow_schema" in tool_names

    @pytest.mark.asyncio
    async def test_cp_filters_non_workflow_tools(self, mock_proxy, tools_with_runner):
        """Non-workflow tools are excluded by CP (not locally)."""
        # Simulate CP doing the filtering and returning only workflow tools
        workflow_tools = [t for t in tools_with_runner if t["name"].startswith("workflow_")]
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": workflow_tools},
        }
        server = make_server(mock_proxy, expose="workflows")

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = await server.handle_request(request)

        tool_names = [t["name"] for t in response["result"]["tools"]]
        assert "python_exec" not in tool_names
        assert "mac__filesystem__read_file" not in tool_names
        assert "slack_post" not in tool_names

    @pytest.mark.asyncio
    async def test_no_runner_required(self, mock_proxy, tools_with_runner):
        """--expose workflows does not require --runner."""
        workflow_tools = [t for t in tools_with_runner if t["name"].startswith("workflow_")]
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": workflow_tools},
        }
        server = make_server(mock_proxy, expose="workflows")
        assert server.runner is None

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = await server.handle_request(request)

        assert len(response["result"]["tools"]) == 3


# =============================================================================
# Zero-tools shutdown tests
# =============================================================================


class TestZeroToolsShutdown:
    """Tests for bridge shutdown when tools/list returns 0 tools.

    When filtering produces zero tools the bridge should:
    1. Return a JSON-RPC error (BRIDGE_EMPTY_TOOLS_ERROR = -32005)
    2. Set shutdown_requested = True so the stdio loop exits
    """

    @pytest.mark.asyncio
    async def test_server_expose_zero_tools_returns_error(self, mock_proxy, tools_with_runner):
        """--expose <server> with no matching tools returns error + shutdown."""
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": tools_with_runner},
        }
        server = make_server(mock_proxy, expose="nonexistent-server", runner="mac")
        assert not server.shutdown_requested

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = await server.handle_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32005
        assert "0 tools" in response["error"]["message"]
        assert server.shutdown_requested is True

    @pytest.mark.asyncio
    async def test_server_expose_zero_tools_after_deregistration(self, mock_proxy):
        """Tools deregistered after initial connect → error + shutdown."""
        # First call: tools present
        tools_v1 = [
            {"name": "mac__github__create_pr", "description": "Create PR", "inputSchema": {}},
        ]
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": tools_v1},
        }
        server = make_server(mock_proxy, expose="github", runner="mac")

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = await server.handle_request(request)
        assert "result" in response
        assert len(response["result"]["tools"]) == 1
        assert not server.shutdown_requested

        # Second call: tools gone (runner disconnected / MCP removed)
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": []},
        }
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        response = await server.handle_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32005
        assert server.shutdown_requested is True

    @pytest.mark.asyncio
    async def test_tag_based_zero_tools_returns_error(self, mock_proxy):
        """Tag-based bridge with 0 matching tools returns error + shutdown."""
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": []},
        }
        server = make_server(mock_proxy, expose="workflows")

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = await server.handle_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32005
        assert "0 tools" in response["error"]["message"]
        assert server.shutdown_requested is True

    @pytest.mark.asyncio
    async def test_tag_based_with_tools_no_shutdown(self, mock_proxy, tools_with_runner):
        """Tag-based bridge with matching tools does NOT trigger shutdown."""
        workflow_tools = [t for t in tools_with_runner if t["name"].startswith("workflow_")]
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": workflow_tools},
        }
        server = make_server(mock_proxy, expose="workflows")

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = await server.handle_request(request)

        assert "result" in response
        assert len(response["result"]["tools"]) > 0
        assert server.shutdown_requested is False

    @pytest.mark.asyncio
    async def test_unfiltered_bridge_no_shutdown_on_empty(self, mock_proxy):
        """Bridge with --tools all (no filter) does NOT shutdown on empty tools.

        An unfiltered bridge (no --expose, no --tags) getting 0 tools is likely
        a transient state (CP just started). Only filtered bridges should fail-fast.
        """
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": []},
        }
        server = make_server(mock_proxy, tools_filter="all")

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = await server.handle_request(request)

        # Unfiltered bridge: returns empty list but does NOT shutdown
        assert "result" in response
        assert response["result"]["tools"] == []
        assert server.shutdown_requested is False

    @pytest.mark.asyncio
    async def test_server_expose_with_tools_no_shutdown(self, mock_proxy, tools_with_runner):
        """--expose <server> with matching tools does NOT trigger shutdown."""
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": tools_with_runner},
        }
        server = make_server(mock_proxy, expose="filesystem", runner="mac")

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = await server.handle_request(request)

        assert "result" in response
        assert len(response["result"]["tools"]) == 2
        assert server.shutdown_requested is False
