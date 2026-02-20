"""HealthMonitor - Periodic health checking for bridge.

Monitors CP health via GET /health and SSE stream status.
Implements 3-strike rule for marking CP as unhealthy.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .proxy import BridgeProxy

logger = logging.getLogger(__name__)

# Default intervals
DEFAULT_CHECK_INTERVAL = 30.0  # Normal health check interval
DEFAULT_DEGRADED_INTERVAL = 10.0  # Interval when SSE is down
DEFAULT_MAX_FAILURES = 3  # Failures before marking unhealthy


class HealthMonitor:
    """Monitors CP health and manages health state.

    Uses periodic GET /health checks and SSE stream status
    to determine if CP is reachable.
    """

    def __init__(
        self,
        proxy: "BridgeProxy",
        check_interval: float = DEFAULT_CHECK_INTERVAL,
        degraded_interval: float = DEFAULT_DEGRADED_INTERVAL,
        max_failures: int = DEFAULT_MAX_FAILURES,
    ):
        """Initialize HealthMonitor.

        Args:
            proxy: BridgeProxy for health checks
            check_interval: Normal interval between checks (seconds)
            degraded_interval: Interval when SSE is down (seconds)
            max_failures: Consecutive failures before unhealthy
        """
        self.proxy = proxy
        self.check_interval = check_interval
        self.degraded_interval = degraded_interval
        self.max_failures = max_failures

        self._is_healthy = True
        self._failure_count = 0
        self._running = False
        self._current_interval = check_interval

    @property
    def is_healthy(self) -> bool:
        """Whether CP is considered healthy."""
        return self._is_healthy

    @property
    def failure_count(self) -> int:
        """Current consecutive failure count."""
        return self._failure_count

    @failure_count.setter
    def failure_count(self, value: int) -> None:
        """Set failure count (for testing)."""
        self._failure_count = value

    @property
    def current_interval(self) -> float:
        """Current check interval."""
        return self._current_interval

    async def run(self) -> None:
        """Run periodic health checks until stopped."""
        self._running = True
        logger.info(f"Starting health monitor (interval: {self.check_interval}s)")

        while self._running:
            try:
                await self._check_health()
            except Exception as e:
                logger.exception(f"Unexpected error in health check: {e}")

            await asyncio.sleep(self._current_interval)

    def stop(self) -> None:
        """Stop the health monitor."""
        self._running = False
        logger.info("Health monitor stopped")

    async def _check_health(self) -> None:
        """Perform a single health check."""
        try:
            result = await self.proxy.health_check()
            self._on_success(result)
        except Exception as e:
            self._on_failure(e)

    def _on_success(self, result: dict) -> None:
        """Handle successful health check."""
        if self._failure_count > 0:
            logger.info(f"Health check recovered after {self._failure_count} failures")

        self._failure_count = 0

        if not self._is_healthy:
            logger.info("CP is healthy again")
            self._is_healthy = True

    def _on_failure(self, error: Exception) -> None:
        """Handle failed health check."""
        self._failure_count += 1
        logger.warning(f"Health check failed ({self._failure_count}/{self.max_failures}): {error}")

        if self._failure_count >= self.max_failures and self._is_healthy:
            logger.error(f"CP marked unhealthy after {self._failure_count} consecutive failures")
            self._is_healthy = False

    def report_sse_healthy(self) -> None:
        """Report that SSE stream is healthy.

        Called when SSE events are received. Resets failure counter
        and restores normal check interval.
        """
        self._failure_count = 0
        self._is_healthy = True
        self._current_interval = self.check_interval

    def report_sse_dropped(self) -> None:
        """Report that SSE stream dropped.

        Called when SSE connection is lost. Increases check frequency
        to detect recovery faster.
        """
        logger.warning("SSE stream dropped, increasing health check frequency")
        self._current_interval = self.degraded_interval
