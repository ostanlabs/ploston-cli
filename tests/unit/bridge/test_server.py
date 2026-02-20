"""Unit tests for BridgeServer - Stdio MCP server facing agents.

TDD RED phase: These tests define the expected behavior of BridgeServer.
All tests should FAIL initially until BridgeServer is implemented.

Test IDs: UT-B020 to UT-B032
"""

from unittest.mock import AsyncMock

import pytest

# Import will fail until we create the module
try:
    from ploston_cli.bridge.proxy import BridgeProxy
    from ploston_cli.bridge.server import BridgeServer
except ImportError:
    BridgeServer = None
    BridgeProxy = None


pytestmark = [pytest.mark.bridge, pytest.mark.bridge_unit]


def skip_if_not_implemented():
    if BridgeServer is None:
        pytest.skip("BridgeServer not implemented yet")


# =============================================================================
# UT-B020 to UT-B023: Initialize Handling Tests
# =============================================================================


class TestBridgeServerInitialize:
    """Tests for handling initialize requests from agents."""

    @pytest.mark.asyncio
    async def test_ut_b020_initialize_forwards_to_cp(self):
        """UT-B020: BridgeServer forwards initialize to CP via proxy."""
        skip_if_not_implemented()

        mock_proxy = AsyncMock(spec=BridgeProxy)
        mock_proxy.initialize.return_value = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": True}},
            "serverInfo": {"name": "ploston-cp", "version": "1.0.0"},
        }

        server = BridgeServer(proxy=mock_proxy)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "claude-desktop", "version": "1.0.0"},
            },
        }

        response = await server.handle_request(request)

        mock_proxy.initialize.assert_called_once()
        assert response["result"]["protocolVersion"] == "2024-11-05"

    @pytest.mark.asyncio
    async def test_ut_b021_initialize_enriches_server_info(self):
        """UT-B021: BridgeServer enriches serverInfo with bridge metadata."""
        skip_if_not_implemented()

        mock_proxy = AsyncMock(spec=BridgeProxy)
        mock_proxy.initialize.return_value = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": True}},
            "serverInfo": {"name": "ploston-cp", "version": "1.0.0"},
        }

        server = BridgeServer(proxy=mock_proxy)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "claude-desktop", "version": "1.0.0"},
            },
        }

        response = await server.handle_request(request)

        # Should report as bridge, not CP directly
        assert response["result"]["serverInfo"]["name"] == "ploston-bridge"
        # Should include CP info in metadata
        assert "cpServerInfo" in response["result"]["serverInfo"]

    @pytest.mark.asyncio
    async def test_ut_b022_initialize_preserves_capabilities(self):
        """UT-B022: BridgeServer preserves CP capabilities in response."""
        skip_if_not_implemented()

        mock_proxy = AsyncMock(spec=BridgeProxy)
        mock_proxy.initialize.return_value = {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": True},
                "prompts": {"listChanged": False},
            },
            "serverInfo": {"name": "ploston-cp", "version": "1.0.0"},
        }

        server = BridgeServer(proxy=mock_proxy)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {}},
        }

        response = await server.handle_request(request)

        assert response["result"]["capabilities"]["tools"]["listChanged"] is True

    @pytest.mark.asyncio
    async def test_ut_b023_initialize_handles_cp_error(self):
        """UT-B023: BridgeServer returns error if CP initialize fails."""
        skip_if_not_implemented()

        mock_proxy = AsyncMock(spec=BridgeProxy)
        mock_proxy.initialize.side_effect = Exception("CP unavailable")

        server = BridgeServer(proxy=mock_proxy)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {}},
        }

        response = await server.handle_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32000


# =============================================================================
# UT-B024 to UT-B026: Tools/List Handling Tests
# =============================================================================


class TestBridgeServerToolsList:
    """Tests for handling tools/list requests."""

    @pytest.mark.asyncio
    async def test_ut_b024_tools_list_forwards_to_cp(self):
        """UT-B024: BridgeServer forwards tools/list to CP."""
        skip_if_not_implemented()

        mock_proxy = AsyncMock(spec=BridgeProxy)
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "test_tool", "description": "A test tool", "inputSchema": {}},
                ]
            },
        }

        server = BridgeServer(proxy=mock_proxy)
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

        response = await server.handle_request(request)

        mock_proxy.send_request.assert_called_once()
        assert len(response["result"]["tools"]) == 1

    @pytest.mark.asyncio
    async def test_ut_b025_tools_list_returns_as_is(self):
        """UT-B025: BridgeServer returns tools/list response unchanged."""
        skip_if_not_implemented()

        mock_proxy = AsyncMock(spec=BridgeProxy)
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {
                        "name": "workflow:scrape_and_summarize",
                        "description": "Scrape and summarize",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"url": {"type": "string"}},
                        },
                    },
                ]
            },
        }

        server = BridgeServer(proxy=mock_proxy)
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

        response = await server.handle_request(request)

        # Tool name should be unchanged (bridge doesn't modify)
        assert response["result"]["tools"][0]["name"] == "workflow:scrape_and_summarize"

    @pytest.mark.asyncio
    async def test_ut_b026_tools_list_preserves_request_id(self):
        """UT-B026: BridgeServer preserves request ID in tools/list response."""
        skip_if_not_implemented()

        mock_proxy = AsyncMock(spec=BridgeProxy)
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 42,
            "result": {"tools": []},
        }

        server = BridgeServer(proxy=mock_proxy)
        request = {"jsonrpc": "2.0", "id": 42, "method": "tools/list", "params": {}}

        response = await server.handle_request(request)

        assert response["id"] == 42


# =============================================================================
# UT-B027 to UT-B029: Tools/Call Handling Tests
# =============================================================================


class TestBridgeServerToolsCall:
    """Tests for handling tools/call requests."""

    @pytest.mark.asyncio
    async def test_ut_b027_tools_call_forwards_to_cp(self):
        """UT-B027: BridgeServer forwards tools/call to CP."""
        skip_if_not_implemented()

        mock_proxy = AsyncMock(spec=BridgeProxy)
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "Tool executed"}]},
        }

        server = BridgeServer(proxy=mock_proxy)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "test_tool", "arguments": {"input": "test"}},
        }

        response = await server.handle_request(request)

        mock_proxy.send_request.assert_called_once()
        assert response["result"]["content"][0]["text"] == "Tool executed"

    @pytest.mark.asyncio
    async def test_ut_b028_tools_call_workflow_forwards_unchanged(self):
        """UT-B028: BridgeServer forwards workflow:* calls unchanged."""
        skip_if_not_implemented()

        mock_proxy = AsyncMock(spec=BridgeProxy)
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "Workflow completed"}]},
        }

        server = BridgeServer(proxy=mock_proxy)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "workflow:scrape_and_summarize",
                "arguments": {"url": "https://example.com"},
            },
        }

        await server.handle_request(request)

        # Verify the request was forwarded with workflow: prefix intact
        call_args = mock_proxy.send_request.call_args[0][0]
        assert call_args["params"]["name"] == "workflow:scrape_and_summarize"

    @pytest.mark.asyncio
    async def test_ut_b029_tools_call_returns_error_result(self):
        """UT-B029: BridgeServer returns tool error results correctly."""
        skip_if_not_implemented()

        mock_proxy = AsyncMock(spec=BridgeProxy)
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [{"type": "text", "text": "Tool failed: timeout"}],
                "isError": True,
            },
        }

        server = BridgeServer(proxy=mock_proxy)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "test_tool", "arguments": {}},
        }

        response = await server.handle_request(request)

        assert response["result"]["isError"] is True


# =============================================================================
# UT-B030 to UT-B031: Notification Forwarding Tests
# =============================================================================


class TestBridgeServerNotifications:
    """Tests for notification forwarding."""

    @pytest.mark.asyncio
    async def test_ut_b030_forwards_tools_list_changed(self):
        """UT-B030: BridgeServer forwards tools/list_changed notifications."""
        skip_if_not_implemented()

        mock_proxy = AsyncMock(spec=BridgeProxy)
        notifications_received = []

        server = BridgeServer(proxy=mock_proxy)
        server.on_notification = lambda n: notifications_received.append(n)

        # Simulate CP sending notification
        await server.handle_cp_notification(
            {
                "jsonrpc": "2.0",
                "method": "notifications/tools/list_changed",
            }
        )

        assert len(notifications_received) == 1
        assert notifications_received[0]["method"] == "notifications/tools/list_changed"

    @pytest.mark.asyncio
    async def test_ut_b031_forwards_progress_notifications(self):
        """UT-B031: BridgeServer forwards progress notifications."""
        skip_if_not_implemented()

        mock_proxy = AsyncMock(spec=BridgeProxy)
        notifications_received = []

        server = BridgeServer(proxy=mock_proxy)
        server.on_notification = lambda n: notifications_received.append(n)

        # Simulate progress notification
        await server.handle_cp_notification(
            {
                "jsonrpc": "2.0",
                "method": "notifications/message",
                "params": {"level": "info", "data": {"step": "scrape", "status": "running"}},
            }
        )

        assert len(notifications_received) == 1
        assert notifications_received[0]["params"]["data"]["step"] == "scrape"


# =============================================================================
# UT-B032: Error Mapping Tests
# =============================================================================


class TestBridgeServerErrorMapping:
    """Tests for error mapping from CP to agent."""

    @pytest.mark.asyncio
    async def test_ut_b032_maps_cp_errors_to_jsonrpc(self):
        """UT-B032: BridgeServer maps CP errors to JSON-RPC errors."""
        skip_if_not_implemented()

        mock_proxy = AsyncMock(spec=BridgeProxy)
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "Tool not found"},
        }

        server = BridgeServer(proxy=mock_proxy)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        }

        response = await server.handle_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32601
