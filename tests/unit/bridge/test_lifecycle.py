"""Unit tests for bridge lifecycle management.

Tests UT-B061 to UT-B079: Startup, shutdown, reconnection, logging.
"""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock

import pytest

from ploston_cli.bridge.lifecycle import BridgeLifecycle
from ploston_cli.bridge.proxy import BridgeProxy, BridgeProxyError


class TestStartupHealthCheck:
    """Tests for startup health check (UT-B061, UT-B062, UT-B063)."""

    @pytest.mark.asyncio
    async def test_ut_b061_startup_health_check_success(self):
        """UT-B061: Startup performs health check."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(return_value={"status": "healthy"})
        proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test"}})

        lifecycle = BridgeLifecycle(proxy=proxy)
        result = await lifecycle.startup()

        assert result is True
        proxy.health_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_ut_b062_startup_retries_on_failure(self):
        """UT-B062: Startup retries health check on failure."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(
            side_effect=[
                BridgeProxyError(code=-32000, message="Fail 1"),
                BridgeProxyError(code=-32000, message="Fail 2"),
                {"status": "healthy"},
            ]
        )
        proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test"}})

        lifecycle = BridgeLifecycle(proxy=proxy, retry_attempts=3, retry_delay=0.01)
        result = await lifecycle.startup()

        assert result is True
        assert proxy.health_check.call_count == 3

    @pytest.mark.asyncio
    async def test_ut_b063_startup_exits_on_all_retries_failed(self):
        """UT-B063: Startup returns False when all retries fail."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(
            side_effect=BridgeProxyError(code=-32000, message="Connection failed")
        )

        lifecycle = BridgeLifecycle(proxy=proxy, retry_attempts=3, retry_delay=0.01)
        result = await lifecycle.startup()

        assert result is False
        assert proxy.health_check.call_count == 3


class TestMCPInitialization:
    """Tests for MCP session initialization (UT-B064, UT-B065)."""

    @pytest.mark.asyncio
    async def test_ut_b064_initializes_mcp_session(self):
        """UT-B064: Startup initializes MCP session with CP."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(return_value={"status": "healthy"})
        proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test-cp"}})

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        proxy.initialize.assert_called_once()
        assert lifecycle.cp_server_info == {"name": "test-cp"}

    @pytest.mark.asyncio
    async def test_ut_b065_subscribes_to_sse(self):
        """UT-B065: Startup subscribes to SSE notifications."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(return_value={"status": "healthy"})
        proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test"}})

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        # SSE subscription is started as background task
        assert lifecycle.sse_task is not None


class TestDegradedMode:
    """Tests for degraded mode (UT-B066)."""

    @pytest.mark.asyncio
    async def test_ut_b066_degraded_mode_when_sse_unavailable(self):
        """UT-B066: Bridge enters degraded mode when SSE unavailable."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(return_value={"status": "healthy"})
        proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test"}})

        async def sse_fails():
            raise BridgeProxyError(code=-32000, message="SSE unavailable")
            yield  # Make it a generator

        proxy.subscribe_notifications = MagicMock(return_value=sse_fails())

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        # Wait for SSE task to fail
        await asyncio.sleep(0.1)

        # Should still be running in degraded mode
        assert lifecycle.is_running is True
        assert lifecycle.is_degraded is True


class TestShutdown:
    """Tests for shutdown (UT-B067, UT-B068, UT-B069, UT-B070)."""

    @pytest.mark.asyncio
    async def test_ut_b067_shutdown_on_sigterm(self):
        """UT-B067: Bridge shuts down on SIGTERM."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(return_value={"status": "healthy"})
        proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test"}})
        proxy.close = AsyncMock()

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        # Simulate SIGTERM
        await lifecycle.shutdown(signal.SIGTERM)

        assert lifecycle.is_running is False
        proxy.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_ut_b068_shutdown_on_sigint(self):
        """UT-B068: Bridge shuts down on SIGINT."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(return_value={"status": "healthy"})
        proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test"}})
        proxy.close = AsyncMock()

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        await lifecycle.shutdown(signal.SIGINT)

        assert lifecycle.is_running is False

    @pytest.mark.asyncio
    async def test_ut_b069_shutdown_on_stdin_close(self):
        """UT-B069: Bridge shuts down when stdin closes."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(return_value={"status": "healthy"})
        proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test"}})
        proxy.close = AsyncMock()

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        await lifecycle.shutdown_on_stdin_close()

        assert lifecycle.is_running is False

    @pytest.mark.asyncio
    async def test_ut_b070_shutdown_drains_requests(self):
        """UT-B070: Shutdown waits for in-flight requests."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(return_value={"status": "healthy"})
        proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test"}})
        proxy.close = AsyncMock()

        lifecycle = BridgeLifecycle(proxy=proxy, drain_timeout=0.1)
        await lifecycle.startup()

        # Simulate in-flight request
        lifecycle.in_flight_count = 1

        # Start shutdown
        shutdown_task = asyncio.create_task(lifecycle.shutdown())

        # Simulate request completing
        await asyncio.sleep(0.05)
        lifecycle.in_flight_count = 0

        await shutdown_task

        assert lifecycle.is_running is False


class TestReconnection:
    """Tests for reconnection (UT-B071, UT-B072, UT-B073)."""

    @pytest.mark.asyncio
    async def test_ut_b071_queues_requests_during_reconnect(self):
        """UT-B071: Requests are queued during reconnection."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(return_value={"status": "healthy"})
        proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test"}})

        lifecycle = BridgeLifecycle(proxy=proxy, max_queue_size=10)
        await lifecycle.startup()

        # Enter reconnecting state
        lifecycle.is_reconnecting = True

        # Queue a request
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        lifecycle.queue_request(request)

        assert lifecycle.request_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_ut_b072_rejects_when_queue_full(self):
        """UT-B072: Rejects requests when queue is full."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(return_value={"status": "healthy"})
        proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test"}})

        lifecycle = BridgeLifecycle(proxy=proxy, max_queue_size=2)
        await lifecycle.startup()
        lifecycle.is_reconnecting = True

        # Fill the queue
        lifecycle.queue_request({"jsonrpc": "2.0", "id": 1, "method": "test"})
        lifecycle.queue_request({"jsonrpc": "2.0", "id": 2, "method": "test"})

        # Third request should be rejected
        result = lifecycle.queue_request({"jsonrpc": "2.0", "id": 3, "method": "test"})

        assert result is False

    @pytest.mark.asyncio
    async def test_ut_b073_drains_queue_after_reconnect(self):
        """UT-B073: Queue is drained after successful reconnect."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(return_value={"status": "healthy"})
        proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test"}})
        proxy.send_request = AsyncMock(return_value={"result": {}})

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()
        lifecycle.is_reconnecting = True

        # Queue requests
        lifecycle.queue_request({"jsonrpc": "2.0", "id": 1, "method": "test"})
        lifecycle.queue_request({"jsonrpc": "2.0", "id": 2, "method": "test"})

        # Reconnect succeeds
        await lifecycle.on_reconnect_success()

        assert lifecycle.is_reconnecting is False
        assert lifecycle.request_queue.empty()
