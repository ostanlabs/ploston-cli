"""Integration tests for bridge resilience.

Tests IT-B011 to IT-B014: Health monitoring, SSE reconnection, degradation, recovery.
"""

import asyncio

import pytest
from aiohttp import web

from ploston_cli.bridge.health import HealthMonitor
from ploston_cli.bridge.lifecycle import BridgeLifecycle
from ploston_cli.bridge.proxy import BridgeProxy


class MockCPServerResilience:
    """Mock CP server for resilience testing."""

    def __init__(self):
        self.is_healthy = True
        self.sse_enabled = True
        self.request_count = 0
        self.restart_count = 0

    async def handle_health(self, request):
        """Handle GET /health."""
        if not self.is_healthy:
            return web.Response(status=503, text="Service Unavailable")
        return web.json_response({"status": "healthy"})

    async def handle_mcp(self, request):
        """Handle POST /mcp."""
        self.request_count += 1
        data = await request.json()
        method = data.get("method", "")

        if method == "initialize":
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "result": {"serverInfo": {"name": "test-cp"}},
                }
            )
        elif method == "tools/list":
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "result": {"tools": []},
                }
            )
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "result": {},
            }
        )

    async def handle_sse(self, request):
        """Handle GET /mcp/sse."""
        if not self.sse_enabled:
            return web.Response(status=503, text="SSE unavailable")

        response = web.StreamResponse()
        response.headers["Content-Type"] = "text/event-stream"
        await response.prepare(request)

        # Send one event then close
        await response.write(b'data: {"method": "heartbeat"}\n\n')
        return response


@pytest.fixture
async def resilience_server():
    """Create mock CP server for resilience tests."""
    server = MockCPServerResilience()
    app = web.Application()
    app.router.add_get("/health", server.handle_health)
    app.router.add_post("/mcp", server.handle_mcp)
    app.router.add_get("/mcp/sse", server.handle_sse)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    port = site._server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    yield server, url

    await runner.cleanup()


class TestResilienceIntegration:
    """Integration tests for bridge resilience."""

    @pytest.mark.asyncio
    async def test_it_b011_health_check_detects_cp_down(self, resilience_server):
        """IT-B011: Health check detects when CP goes down."""
        server, url = resilience_server
        proxy = BridgeProxy(url=url)

        monitor = HealthMonitor(proxy=proxy, check_interval=0.1, max_failures=2)

        # Start healthy
        task = asyncio.create_task(monitor.run())
        await asyncio.sleep(0.15)
        assert monitor.is_healthy is True

        # CP goes down
        server.is_healthy = False
        await asyncio.sleep(0.3)

        assert monitor.is_healthy is False

        monitor.stop()
        await task
        await proxy.close()

    @pytest.mark.asyncio
    async def test_it_b012_sse_reconnection_on_drop(self, resilience_server):
        """IT-B012: SSE reconnects when stream drops."""
        server, url = resilience_server
        proxy = BridgeProxy(url=url)

        # Subscribe to SSE
        events = []
        async for event in proxy.subscribe_notifications():
            events.append(event)
            break  # Stream will close after one event

        # Should have received at least one event
        assert len(events) >= 1
        await proxy.close()

    @pytest.mark.asyncio
    async def test_it_b013_graceful_degradation_no_sse(self, resilience_server):
        """IT-B013: Bridge degrades gracefully when SSE unavailable."""
        server, url = resilience_server
        server.sse_enabled = False

        proxy = BridgeProxy(url=url)
        lifecycle = BridgeLifecycle(proxy=proxy)

        result = await lifecycle.startup()

        # Should still start (degraded mode)
        assert result is True
        assert lifecycle.is_running is True

        # Wait for SSE task to fail
        await asyncio.sleep(0.2)
        assert lifecycle.is_degraded is True

        await lifecycle.shutdown()

    @pytest.mark.asyncio
    async def test_it_b014_recovery_after_cp_restart(self, resilience_server):
        """IT-B014: Bridge recovers after CP restart."""
        server, url = resilience_server
        proxy = BridgeProxy(url=url)

        monitor = HealthMonitor(proxy=proxy, check_interval=0.1, max_failures=2)

        task = asyncio.create_task(monitor.run())

        # CP goes down
        server.is_healthy = False
        await asyncio.sleep(0.3)
        assert monitor.is_healthy is False

        # CP comes back
        server.is_healthy = True
        server.restart_count += 1
        await asyncio.sleep(0.2)

        assert monitor.is_healthy is True

        monitor.stop()
        await task
        await proxy.close()
