"""Heartbeat mechanism for runner connection.

Handles:
- Periodic heartbeat sending
- Heartbeat timeout detection
- Connection health monitoring
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .types import JSONRPCNotification, RunnerMethods

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class HeartbeatManager:
    """Manages heartbeat mechanism for runner connection.

    Sends periodic heartbeats to CP and detects connection issues
    when heartbeats fail.
    """

    def __init__(
        self,
        interval: float = 30.0,
        timeout: float = 10.0,
        on_timeout: Callable[[], Awaitable[None]] | None = None,
    ):
        """Initialize heartbeat manager.

        Args:
            interval: Seconds between heartbeats
            timeout: Seconds to wait for heartbeat acknowledgment
            on_timeout: Callback when heartbeat times out
        """
        self._interval = interval
        self._timeout = timeout
        self._on_timeout = on_timeout

        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._last_sent: datetime | None = None
        self._last_ack: datetime | None = None
        self._consecutive_failures = 0
        self._send_func: Callable[[dict], Awaitable[None]] | None = None

    @property
    def interval(self) -> float:
        """Get heartbeat interval in seconds."""
        return self._interval

    @property
    def is_running(self) -> bool:
        """Check if heartbeat loop is running."""
        return self._running

    @property
    def last_sent(self) -> datetime | None:
        """Get timestamp of last sent heartbeat."""
        return self._last_sent

    @property
    def last_ack(self) -> datetime | None:
        """Get timestamp of last acknowledged heartbeat."""
        return self._last_ack

    @property
    def consecutive_failures(self) -> int:
        """Get count of consecutive heartbeat failures."""
        return self._consecutive_failures

    def set_send_func(self, func: Callable[[dict], Awaitable[None]]) -> None:
        """Set the function to send messages.

        Args:
            func: Async function that sends a message dict
        """
        self._send_func = func

    def create_heartbeat_message(self) -> JSONRPCNotification:
        """Create heartbeat notification message.

        Returns:
            JSONRPCNotification for heartbeat
        """
        now = datetime.now(UTC)
        return JSONRPCNotification(
            method=RunnerMethods.HEARTBEAT,
            params={
                "timestamp": now.isoformat(),
            },
        )

    async def start(self) -> None:
        """Start the heartbeat loop."""
        if self._running:
            logger.warning("Heartbeat already running")
            return

        if not self._send_func:
            raise RuntimeError("Send function not set")

        self._running = True
        self._consecutive_failures = 0
        self._task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"Heartbeat started (interval: {self._interval}s)")

    async def stop(self) -> None:
        """Stop the heartbeat loop."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("Heartbeat stopped")

    async def _heartbeat_loop(self) -> None:
        """Background task that sends periodic heartbeats."""
        while self._running:
            try:
                await asyncio.sleep(self._interval)

                if not self._running:
                    break

                await self._send_heartbeat()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                self._consecutive_failures += 1

                if self._consecutive_failures >= 3 and self._on_timeout:
                    logger.warning("Multiple heartbeat failures, triggering timeout")
                    await self._on_timeout()

    async def _send_heartbeat(self) -> None:
        """Send a single heartbeat."""
        if not self._send_func:
            return

        message = self.create_heartbeat_message()
        self._last_sent = datetime.now(UTC)

        try:
            await self._send_func(message.to_dict())
            self._consecutive_failures = 0
            logger.debug(f"Heartbeat sent at {self._last_sent.isoformat()}")
        except Exception as e:
            self._consecutive_failures += 1
            logger.warning(f"Failed to send heartbeat: {e}")
            raise

    def acknowledge(self) -> None:
        """Record heartbeat acknowledgment."""
        self._last_ack = datetime.now(UTC)
        self._consecutive_failures = 0
        logger.debug(f"Heartbeat acknowledged at {self._last_ack.isoformat()}")

    def reset(self) -> None:
        """Reset heartbeat state."""
        self._last_sent = None
        self._last_ack = None
        self._consecutive_failures = 0


class HeartbeatTimeoutError(Exception):
    """Heartbeat timeout detected."""

    pass
