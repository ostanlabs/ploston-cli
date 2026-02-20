"""BridgeLifecycle - Manages bridge startup, shutdown, and reconnection.

Handles:
- Startup health check with retry
- MCP session initialization
- SSE subscription
- Graceful shutdown
- Request queuing during reconnection
"""

import asyncio
import logging
import signal
from queue import Full, Queue
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .proxy import BridgeProxy

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_DELAY = 1.0
DEFAULT_DRAIN_TIMEOUT = 5.0
DEFAULT_MAX_QUEUE_SIZE = 10


class BridgeLifecycle:
    """Manages bridge lifecycle: startup, shutdown, reconnection."""

    def __init__(
        self,
        proxy: "BridgeProxy",
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        drain_timeout: float = DEFAULT_DRAIN_TIMEOUT,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
    ):
        """Initialize BridgeLifecycle.

        Args:
            proxy: BridgeProxy for CP communication
            retry_attempts: Number of startup retry attempts
            retry_delay: Delay between retries (seconds)
            drain_timeout: Max time to wait for in-flight requests (seconds)
            max_queue_size: Max requests to queue during reconnection
        """
        self.proxy = proxy
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.drain_timeout = drain_timeout
        self.max_queue_size = max_queue_size

        self._is_running = False
        self._is_degraded = False
        self._is_reconnecting = False
        self._in_flight_count = 0
        self._cp_server_info: Optional[dict] = None
        self._sse_task: Optional[asyncio.Task] = None
        self._request_queue: Queue = Queue(maxsize=max_queue_size)

    @property
    def is_running(self) -> bool:
        """Whether bridge is running."""
        return self._is_running

    @property
    def is_degraded(self) -> bool:
        """Whether bridge is in degraded mode (no SSE)."""
        return self._is_degraded

    @property
    def is_reconnecting(self) -> bool:
        """Whether bridge is reconnecting."""
        return self._is_reconnecting

    @is_reconnecting.setter
    def is_reconnecting(self, value: bool) -> None:
        """Set reconnecting state."""
        self._is_reconnecting = value

    @property
    def in_flight_count(self) -> int:
        """Number of in-flight requests."""
        return self._in_flight_count

    @in_flight_count.setter
    def in_flight_count(self, value: int) -> None:
        """Set in-flight count."""
        self._in_flight_count = value

    @property
    def cp_server_info(self) -> Optional[dict]:
        """CP server info from initialization."""
        return self._cp_server_info

    @property
    def sse_task(self) -> Optional[asyncio.Task]:
        """SSE subscription task."""
        return self._sse_task

    @property
    def request_queue(self) -> Queue:
        """Request queue for reconnection."""
        return self._request_queue

    async def startup(self) -> bool:
        """Perform startup sequence.

        Returns:
            True if startup succeeded, False otherwise.
        """
        logger.info("Starting bridge...")

        # Health check with retry
        for attempt in range(self.retry_attempts):
            try:
                await self.proxy.health_check()
                logger.info("Health check passed")
                break
            except Exception as e:
                logger.warning(
                    f"Health check failed (attempt {attempt + 1}/{self.retry_attempts}): {e}"
                )
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(self.retry_delay * (2**attempt))
        else:
            logger.error("All health check retries failed")
            return False

        # Initialize MCP session
        try:
            result = await self.proxy.initialize()
            self._cp_server_info = result.get("serverInfo")
            logger.info(f"MCP session initialized with CP: {self._cp_server_info}")
        except Exception as e:
            logger.error(f"MCP initialization failed: {e}")
            return False

        # Start SSE subscription (non-blocking)
        self._sse_task = asyncio.create_task(self._run_sse_subscription())
        self._is_running = True

        logger.info("Bridge started successfully")
        return True

    async def _run_sse_subscription(self) -> None:
        """Run SSE subscription in background."""
        try:
            async for event in self.proxy.subscribe_notifications():
                logger.debug(f"SSE event: {event}")
        except Exception as e:
            logger.warning(f"SSE subscription failed: {e}")
            self._is_degraded = True

    async def shutdown(self, sig: Optional[signal.Signals] = None) -> None:
        """Perform graceful shutdown."""
        if sig:
            logger.info(f"Received signal {sig.name}, shutting down...")
        else:
            logger.info("Shutting down...")

        self._is_running = False

        # Wait for in-flight requests
        await self._drain_requests()

        # Cancel SSE task
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass

        # Close proxy
        await self.proxy.close()
        logger.info("Bridge shutdown complete")

    async def shutdown_on_stdin_close(self) -> None:
        """Shutdown when stdin closes."""
        logger.info("stdin closed, shutting down...")
        await self.shutdown()

    async def _drain_requests(self) -> None:
        """Wait for in-flight requests to complete."""
        if self._in_flight_count == 0:
            return

        logger.info(f"Waiting for {self._in_flight_count} in-flight requests...")
        start = asyncio.get_event_loop().time()

        while self._in_flight_count > 0:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed >= self.drain_timeout:
                logger.warning(f"Drain timeout, {self._in_flight_count} requests still in-flight")
                break
            await asyncio.sleep(0.1)

        logger.info("Request drain complete")

    def queue_request(self, request: dict) -> bool:
        """Queue a request during reconnection.

        Args:
            request: JSON-RPC request to queue

        Returns:
            True if queued, False if queue is full
        """
        try:
            self._request_queue.put_nowait(request)
            logger.debug(f"Queued request {request.get('id')}")
            return True
        except Full:
            logger.warning("Request queue full, rejecting request")
            return False

    async def on_reconnect_success(self) -> None:
        """Handle successful reconnection."""
        logger.info("Reconnection successful, draining queue...")
        self._is_reconnecting = False

        # Drain queued requests
        while not self._request_queue.empty():
            try:
                request = self._request_queue.get_nowait()
                await self.proxy.send_request(request)
                logger.debug(f"Drained request {request.get('id')}")
            except Exception as e:
                logger.error(f"Failed to drain request: {e}")
