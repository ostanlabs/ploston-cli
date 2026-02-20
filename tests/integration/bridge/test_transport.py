"""Integration tests for bridge transport translation.

Tests IT-B001 to IT-B008: Full roundtrip tests with mock CP server.
"""

import asyncio
import json

import pytest
from aiohttp import web

from ploston_cli.bridge.proxy import BridgeProxy
from ploston_cli.bridge.server import BridgeServer


class MockCPServer:
    """Mock Control Plane server for integration tests."""

    def __init__(self):
        self.app = web.Application()
        self.app.router.add_post("/mcp", self.handle_mcp)
        self.app.router.add_get("/mcp/sse", self.handle_sse)
        self.app.router.add_get("/health", self.handle_health)
        self.runner = None
        self.site = None
        self.port = None
        self.requests = []
        self.responses = {}
        self.sse_events = []
        self.require_auth = False
        self.expected_token = None

    async def start(self, port: int = 0) -> str:
        """Start the mock server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", port)
        await self.site.start()
        self.port = self.site._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{self.port}"

    async def stop(self):
        """Stop the mock server."""
        if self.runner:
            await self.runner.cleanup()

    async def handle_mcp(self, request: web.Request) -> web.Response:
        """Handle POST /mcp requests."""
        # Check auth if required
        if self.require_auth:
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or auth[7:] != self.expected_token:
                return web.json_response(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32001, "message": "Unauthorized"},
                    },
                    status=401,
                )

        body = await request.json()
        self.requests.append(body)

        method = body.get("method", "")
        request_id = body.get("id")

        # Check for pre-configured response
        if method in self.responses:
            response = self.responses[method]
            if callable(response):
                response = response(body)
            return web.json_response({"jsonrpc": "2.0", "id": request_id, **response})

        # Default responses
        if method == "initialize":
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "mock-cp", "version": "1.0.0"},
                    },
                }
            )
        elif method == "tools/list":
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"tools": [{"name": "test_tool", "description": "A test tool"}]},
                }
            )
        elif method == "tools/call":
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [{"type": "text", "text": "Tool executed"}]},
                }
            )

        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        )

    async def handle_sse(self, request: web.Request) -> web.StreamResponse:
        """Handle GET /mcp/sse requests."""
        response = web.StreamResponse()
        response.content_type = "text/event-stream"
        await response.prepare(request)

        for event in self.sse_events:
            await response.write(f"data: {json.dumps(event)}\n\n".encode())

        return response

    async def handle_health(self, request: web.Request) -> web.Response:
        """Handle GET /health requests."""
        return web.json_response({"status": "healthy"})


@pytest.fixture
async def mock_cp():
    """Fixture providing a mock CP server."""
    server = MockCPServer()
    url = await server.start()
    yield server, url
    await server.stop()


class TestTransportIntegration:
    """Integration tests for transport translation (IT-B001 to IT-B008)."""

    @pytest.mark.asyncio
    async def test_it_b001_full_initialize_handshake(self, mock_cp):
        """IT-B001: Full initialize handshake through bridge."""
        server, url = mock_cp
        proxy = BridgeProxy(url=url)
        bridge = BridgeServer(proxy=proxy)

        request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        response = await bridge.handle_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response
        assert response["result"]["serverInfo"]["name"] == "ploston-bridge"
        assert "cpServerInfo" in response["result"]["serverInfo"]
        await proxy.close()

    @pytest.mark.asyncio
    async def test_it_b002_full_tools_list_roundtrip(self, mock_cp):
        """IT-B002: Full tools/list roundtrip through bridge."""
        server, url = mock_cp
        proxy = BridgeProxy(url=url)
        bridge = BridgeServer(proxy=proxy)

        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        response = await bridge.handle_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 2
        assert "result" in response
        assert "tools" in response["result"]
        assert len(response["result"]["tools"]) == 1
        assert response["result"]["tools"][0]["name"] == "test_tool"
        await proxy.close()

    @pytest.mark.asyncio
    async def test_it_b003_full_tools_call_roundtrip(self, mock_cp):
        """IT-B003: Full tools/call roundtrip through bridge."""
        server, url = mock_cp
        proxy = BridgeProxy(url=url)
        bridge = BridgeServer(proxy=proxy)

        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "test_tool", "arguments": {"input": "test"}},
        }
        response = await bridge.handle_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 3
        assert "result" in response
        assert response["result"]["content"][0]["text"] == "Tool executed"
        await proxy.close()

    @pytest.mark.asyncio
    async def test_it_b004_tools_changed_notification_flow(self, mock_cp):
        """IT-B004: tools/list_changed notification flow."""
        server, url = mock_cp
        server.sse_events = [
            {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"},
        ]

        proxy = BridgeProxy(url=url)
        bridge = BridgeServer(proxy=proxy)

        notifications = []
        bridge.on_notification = lambda n: notifications.append(n)

        # Subscribe and receive notification
        async for event in proxy.subscribe_notifications():
            await bridge.handle_cp_notification(event)
            break  # Just get first event

        assert len(notifications) == 1
        assert notifications[0]["method"] == "notifications/tools/list_changed"
        await proxy.close()

    @pytest.mark.asyncio
    async def test_it_b005_multiple_concurrent_tool_calls(self, mock_cp):
        """IT-B005: Multiple concurrent tool calls."""
        server, url = mock_cp
        proxy = BridgeProxy(url=url)
        bridge = BridgeServer(proxy=proxy)

        # Send multiple concurrent requests
        requests = [
            {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": f"tool_{i}"}}
            for i in range(5)
        ]

        responses = await asyncio.gather(*[bridge.handle_request(r) for r in requests])

        # All should succeed with correct IDs
        for i, response in enumerate(responses):
            assert response["id"] == i
            assert "result" in response

        await proxy.close()

    @pytest.mark.asyncio
    async def test_it_b006_auth_token_forwarding(self, mock_cp):
        """IT-B006: Auth token forwarding to CP."""
        server, url = mock_cp
        server.require_auth = True
        server.expected_token = "test_token_123"

        proxy = BridgeProxy(url=url, token="test_token_123")
        bridge = BridgeServer(proxy=proxy)

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = await bridge.handle_request(request)

        assert "result" in response
        assert "tools" in response["result"]
        await proxy.close()

    @pytest.mark.asyncio
    async def test_it_b007_no_auth_still_works(self, mock_cp):
        """IT-B007: No auth still works when CP doesn't require it."""
        server, url = mock_cp
        # server.require_auth = False (default)

        proxy = BridgeProxy(url=url)  # No token
        bridge = BridgeServer(proxy=proxy)

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = await bridge.handle_request(request)

        assert "result" in response
        await proxy.close()

    @pytest.mark.asyncio
    async def test_it_b008_cp_error_mapped_to_agent(self, mock_cp):
        """IT-B008: CP error mapped to agent."""
        server, url = mock_cp
        server.responses["tools/call"] = {
            "error": {"code": -32000, "message": "Workflow execution failed"}
        }

        proxy = BridgeProxy(url=url)
        bridge = BridgeServer(proxy=proxy)

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "failing_tool"},
        }
        response = await bridge.handle_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32000
        assert "Workflow execution failed" in response["error"]["message"]
        await proxy.close()
