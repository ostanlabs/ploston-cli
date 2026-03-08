"""Unit tests for bridge lifecycle management.

Tests UT-B061 to UT-B079: Startup, shutdown, reconnection, logging.
"""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock

import pytest

from ploston_cli.bridge.lifecycle import BridgeLifecycle
from ploston_cli.bridge.proxy import BridgeProxy, BridgeProxyError


async def _cleanup_lifecycle(lifecycle: BridgeLifecycle) -> None:
    """Cancel SSE task to prevent hangs in tests."""
    lifecycle._is_running = False
    if lifecycle._sse_task and not lifecycle._sse_task.done():
        lifecycle._sse_task.cancel()
        try:
            await lifecycle._sse_task
        except (asyncio.CancelledError, Exception):
            pass


def _make_empty_sse_proxy():
    """Create a proxy mock with an SSE subscription that waits (non-busy) until cancelled."""
    proxy = MagicMock(spec=BridgeProxy)
    proxy.health_check = AsyncMock(return_value={"status": "healthy"})
    proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test"}})
    proxy.close = AsyncMock()

    async def _empty_sse():
        # Wait forever (cancellable) — simulates a live SSE connection
        await asyncio.sleep(3600)
        yield  # make it an async generator  # noqa: unreachable

    proxy.subscribe_notifications = MagicMock(side_effect=lambda: _empty_sse())
    return proxy


class TestStartupHealthCheck:
    """Tests for startup health check (UT-B061, UT-B062, UT-B063)."""

    @pytest.mark.asyncio
    async def test_ut_b061_startup_health_check_success(self):
        """UT-B061: Startup performs health check."""
        proxy = _make_empty_sse_proxy()

        lifecycle = BridgeLifecycle(proxy=proxy)
        result = await lifecycle.startup()

        assert result is True
        proxy.health_check.assert_called_once()
        await _cleanup_lifecycle(lifecycle)

    @pytest.mark.asyncio
    async def test_ut_b062_startup_retries_on_failure(self):
        """UT-B062: Startup retries health check on failure."""
        proxy = _make_empty_sse_proxy()
        proxy.health_check = AsyncMock(
            side_effect=[
                BridgeProxyError(code=-32000, message="Fail 1"),
                BridgeProxyError(code=-32000, message="Fail 2"),
                {"status": "healthy"},
            ]
        )

        lifecycle = BridgeLifecycle(proxy=proxy, retry_attempts=3, retry_delay=0.01)
        result = await lifecycle.startup()

        assert result is True
        assert proxy.health_check.call_count == 3
        await _cleanup_lifecycle(lifecycle)

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
        proxy = _make_empty_sse_proxy()
        proxy.initialize = AsyncMock(return_value={"serverInfo": {"name": "test-cp"}})

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        proxy.initialize.assert_called_once()
        assert lifecycle.cp_server_info == {"name": "test-cp"}
        await _cleanup_lifecycle(lifecycle)

    @pytest.mark.asyncio
    async def test_ut_b065_subscribes_to_sse(self):
        """UT-B065: Startup subscribes to SSE notifications."""
        proxy = _make_empty_sse_proxy()

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        # SSE subscription is started as background task
        assert lifecycle.sse_task is not None
        await _cleanup_lifecycle(lifecycle)


class TestDegradedMode:
    """Tests for degraded mode (UT-B066)."""

    @pytest.mark.asyncio
    async def test_ut_b066_degraded_mode_when_sse_unavailable(self):
        """UT-B066: Bridge enters degraded mode when SSE unavailable."""
        proxy = _make_empty_sse_proxy()

        async def sse_fails():
            raise BridgeProxyError(code=-32000, message="SSE unavailable")
            yield  # noqa: unreachable - make it an async generator

        proxy.subscribe_notifications = MagicMock(side_effect=lambda: sse_fails())

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        # Wait for SSE task to fail and enter degraded mode
        await asyncio.sleep(0.1)

        # Should still be running in degraded mode
        assert lifecycle.is_running is True
        assert lifecycle.is_degraded is True
        await _cleanup_lifecycle(lifecycle)


class TestShutdown:
    """Tests for shutdown (UT-B067, UT-B068, UT-B069, UT-B070)."""

    @pytest.mark.asyncio
    async def test_ut_b067_shutdown_on_sigterm(self):
        """UT-B067: Bridge shuts down on SIGTERM."""
        proxy = _make_empty_sse_proxy()

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        # Simulate SIGTERM
        await lifecycle.shutdown(signal.SIGTERM)

        assert lifecycle.is_running is False
        proxy.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_ut_b068_shutdown_on_sigint(self):
        """UT-B068: Bridge shuts down on SIGINT."""
        proxy = _make_empty_sse_proxy()

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        await lifecycle.shutdown(signal.SIGINT)

        assert lifecycle.is_running is False

    @pytest.mark.asyncio
    async def test_ut_b069_shutdown_on_stdin_close(self):
        """UT-B069: Bridge shuts down when stdin closes."""
        proxy = _make_empty_sse_proxy()

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        await lifecycle.shutdown_on_stdin_close()

        assert lifecycle.is_running is False

    @pytest.mark.asyncio
    async def test_ut_b070_shutdown_drains_requests(self):
        """UT-B070: Shutdown waits for in-flight requests."""
        proxy = _make_empty_sse_proxy()

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
        proxy = _make_empty_sse_proxy()

        lifecycle = BridgeLifecycle(proxy=proxy, max_queue_size=10)
        await lifecycle.startup()

        # Enter reconnecting state
        lifecycle.is_reconnecting = True

        # Queue a request
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        lifecycle.queue_request(request)

        assert lifecycle.request_queue.qsize() == 1
        await _cleanup_lifecycle(lifecycle)

    @pytest.mark.asyncio
    async def test_ut_b072_rejects_when_queue_full(self):
        """UT-B072: Rejects requests when queue is full."""
        proxy = _make_empty_sse_proxy()

        lifecycle = BridgeLifecycle(proxy=proxy, max_queue_size=2)
        await lifecycle.startup()
        lifecycle.is_reconnecting = True

        # Fill the queue
        lifecycle.queue_request({"jsonrpc": "2.0", "id": 1, "method": "test"})
        lifecycle.queue_request({"jsonrpc": "2.0", "id": 2, "method": "test"})

        # Third request should be rejected
        result = lifecycle.queue_request({"jsonrpc": "2.0", "id": 3, "method": "test"})

        assert result is False
        await _cleanup_lifecycle(lifecycle)

    @pytest.mark.asyncio
    async def test_ut_b073_drains_queue_after_reconnect(self):
        """UT-B073: Queue is drained after successful reconnect."""
        proxy = _make_empty_sse_proxy()
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
        await _cleanup_lifecycle(lifecycle)


class TestSSEReconnection:
    """Tests for unlimited SSE reconnection."""

    @pytest.mark.asyncio
    async def test_sse_retries_after_failure(self):
        """SSE subscription retries after initial failure."""
        proxy = _make_empty_sse_proxy()

        async def sse_always_fails():
            raise BridgeProxyError(code=-32000, message="SSE unavailable")
            yield  # noqa: unreachable - make it an async generator

        proxy.subscribe_notifications = MagicMock(side_effect=lambda: sse_always_fails())

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        # Wait for first SSE failure to enter degraded mode
        await asyncio.sleep(0.2)

        assert lifecycle.is_degraded is True
        assert lifecycle.is_running is True
        await _cleanup_lifecycle(lifecycle)

    @pytest.mark.asyncio
    async def test_sse_recovery_clears_degraded(self):
        """SSE degraded flag is cleared when subscription recovers."""
        proxy = _make_empty_sse_proxy()

        call_count = 0

        async def sse_fail_then_recover():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise BridgeProxyError(code=-32000, message="SSE unavailable")
            # Second call: yield one event then wait forever (cancellable)
            yield {"type": "test", "data": "recovered"}
            await asyncio.sleep(3600)

        proxy.subscribe_notifications = MagicMock(side_effect=sse_fail_then_recover)

        lifecycle = BridgeLifecycle(proxy=proxy)
        await lifecycle.startup()

        # Wait for first failure + 1s retry delay + recovery
        await asyncio.sleep(1.5)

        # After yielding an event, degraded should be cleared
        assert lifecycle.is_degraded is False
        assert lifecycle.is_running is True
        await _cleanup_lifecycle(lifecycle)
