"""Unit tests for HealthMonitor.

Tests UT-B053 to UT-B060: Health monitoring and state management.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ploston_cli.bridge.health import HealthMonitor
from ploston_cli.bridge.proxy import BridgeProxy, BridgeProxyError


class TestHealthMonitorInitialState:
    """Tests for HealthMonitor initial state (UT-B053)."""

    def test_ut_b053_initial_state_is_healthy(self):
        """UT-B053: HealthMonitor starts in healthy state."""
        proxy = MagicMock(spec=BridgeProxy)
        monitor = HealthMonitor(proxy=proxy)

        assert monitor.is_healthy is True
        assert monitor.failure_count == 0


class TestHealthMonitorPeriodicCheck:
    """Tests for periodic health check (UT-B054)."""

    @pytest.mark.asyncio
    async def test_ut_b054_periodic_check_interval(self):
        """UT-B054: Health check runs at configured interval."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(return_value={"status": "healthy"})

        monitor = HealthMonitor(proxy=proxy, check_interval=0.1)

        # Run for a short time
        task = asyncio.create_task(monitor.run())
        await asyncio.sleep(0.35)
        monitor.stop()
        await task

        # Should have checked at least 3 times (0.1s interval over 0.35s)
        assert proxy.health_check.call_count >= 3


class TestHealthMonitorFailures:
    """Tests for failure handling (UT-B055, UT-B056)."""

    @pytest.mark.asyncio
    async def test_ut_b055_single_failure_still_healthy(self):
        """UT-B055: Single failure keeps monitor healthy."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(
            side_effect=[
                {"status": "healthy"},
                BridgeProxyError(code=-32000, message="Connection failed"),
                {"status": "healthy"},
            ]
        )

        monitor = HealthMonitor(proxy=proxy, check_interval=0.05)

        task = asyncio.create_task(monitor.run())
        await asyncio.sleep(0.2)
        monitor.stop()
        await task

        assert monitor.is_healthy is True
        assert monitor.failure_count <= 1

    @pytest.mark.asyncio
    async def test_ut_b056_three_failures_marks_unhealthy(self):
        """UT-B056: Three consecutive failures marks monitor unhealthy."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(
            side_effect=BridgeProxyError(code=-32000, message="Connection failed")
        )

        monitor = HealthMonitor(proxy=proxy, check_interval=0.05, max_failures=3)

        task = asyncio.create_task(monitor.run())
        await asyncio.sleep(0.25)
        monitor.stop()
        await task

        assert monitor.is_healthy is False
        assert monitor.failure_count >= 3


class TestHealthMonitorRecovery:
    """Tests for recovery (UT-B057)."""

    @pytest.mark.asyncio
    async def test_ut_b057_recovery_resets_counter(self):
        """UT-B057: Successful check after failures resets counter."""
        proxy = MagicMock(spec=BridgeProxy)
        # After recovery, keep returning healthy
        proxy.health_check = AsyncMock(
            side_effect=[
                BridgeProxyError(code=-32000, message="Fail 1"),
                BridgeProxyError(code=-32000, message="Fail 2"),
                {"status": "healthy"},  # Recovery
                {"status": "healthy"},  # Stay healthy
                {"status": "healthy"},  # Stay healthy
            ]
        )

        monitor = HealthMonitor(proxy=proxy, check_interval=0.05, max_failures=3)

        task = asyncio.create_task(monitor.run())
        await asyncio.sleep(0.2)
        monitor.stop()
        await task

        assert monitor.is_healthy is True
        assert monitor.failure_count == 0


class TestHealthMonitorSSE:
    """Tests for SSE health reporting (UT-B058, UT-B059)."""

    def test_ut_b058_sse_event_resets_counter(self):
        """UT-B058: SSE event resets failure counter."""
        proxy = MagicMock(spec=BridgeProxy)
        monitor = HealthMonitor(proxy=proxy)
        monitor.failure_count = 2

        monitor.report_sse_healthy()

        assert monitor.failure_count == 0
        assert monitor.is_healthy is True

    def test_ut_b059_sse_drop_increases_frequency(self):
        """UT-B059: SSE drop increases check frequency."""
        proxy = MagicMock(spec=BridgeProxy)
        monitor = HealthMonitor(proxy=proxy, check_interval=30.0, degraded_interval=10.0)

        monitor.report_sse_dropped()

        assert monitor.current_interval == 10.0


class TestHealthMonitorLogging:
    """Tests for logging (UT-B060)."""

    @pytest.mark.asyncio
    async def test_ut_b060_logs_state_change(self):
        """UT-B060: State changes are logged."""
        proxy = MagicMock(spec=BridgeProxy)
        proxy.health_check = AsyncMock(
            side_effect=BridgeProxyError(code=-32000, message="Connection failed")
        )

        monitor = HealthMonitor(proxy=proxy, check_interval=0.05, max_failures=3)

        with patch("ploston_cli.bridge.health.logger") as mock_logger:
            task = asyncio.create_task(monitor.run())
            await asyncio.sleep(0.25)
            monitor.stop()
            await task

            # Should log warning for failures and error when unhealthy
            assert mock_logger.warning.called or mock_logger.error.called
