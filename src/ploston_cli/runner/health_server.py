"""Health server for the runner.

Provides a minimal HTTP server on localhost:9876 for health checks.
This is localhost-only, not network-exposed.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

HEALTH_PORT = 9876
HEALTH_HOST = "127.0.0.1"


@dataclass
class HealthStatus:
    """Health status data for the runner."""

    name: str = "unknown"
    cp_connected: bool = False
    cp_url: str = ""
    start_time: float = field(default_factory=time.time)
    available_tools: int = 0
    unavailable_tools: int = 0
    tools: dict[str, str] = field(default_factory=dict)
    last_config_received: str | None = None
    version: str = "1.0.0"

    @property
    def status(self) -> str:
        """Get overall health status."""
        if not self.cp_connected:
            return "unhealthy"
        if self.unavailable_tools > 0:
            return "degraded"
        return "healthy"

    @property
    def uptime_seconds(self) -> int:
        """Get uptime in seconds."""
        return int(time.time() - self.start_time)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON response."""
        return {
            "status": self.status,
            "name": self.name,
            "cp_connected": self.cp_connected,
            "cp_url": self.cp_url,
            "uptime_seconds": self.uptime_seconds,
            "available_tools": self.available_tools,
            "unavailable_tools": self.unavailable_tools,
            "tools": self.tools,
            "last_config_received": self.last_config_received,
            "version": self.version,
        }


class HealthServer:
    """Minimal HTTP server for health checks.

    Runs as a task in the runner's asyncio event loop.
    Only responds to GET /health requests.
    """

    def __init__(self, health_status: HealthStatus):
        """Initialize health server.

        Args:
            health_status: Shared health status object (updated by runner)
        """
        self._health_status = health_status
        self._server: asyncio.Server | None = None
        self._running = False

    async def start(self) -> None:
        """Start the health server."""
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_connection,
            HEALTH_HOST,
            HEALTH_PORT,
        )
        logger.info(f"Health server started on http://{HEALTH_HOST}:{HEALTH_PORT}")

    async def stop(self) -> None:
        """Stop the health server."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        logger.info("Health server stopped")

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle incoming HTTP connection."""
        try:
            # Read request line
            request_line = await asyncio.wait_for(
                reader.readline(),
                timeout=5.0,
            )
            request_str = request_line.decode("utf-8").strip()

            # Parse request
            parts = request_str.split(" ")
            if len(parts) >= 2:
                method, path = parts[0], parts[1]
            else:
                method, path = "GET", "/"

            # Read headers (we don't need them, just consume)
            while True:
                line = await reader.readline()
                if line == b"\r\n" or line == b"\n" or line == b"":
                    break

            # Handle request
            if method == "GET" and path == "/health":
                response_body = json.dumps(self._health_status.to_dict())
                status_line = "HTTP/1.1 200 OK"
            else:
                response_body = json.dumps({"error": "Not Found"})
                status_line = "HTTP/1.1 404 Not Found"

            # Send response
            response = (
                f"{status_line}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(response_body)}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
                f"{response_body}"
            )
            writer.write(response.encode("utf-8"))
            await writer.drain()

        except asyncio.TimeoutError:
            logger.debug("Health check connection timed out")
        except Exception as e:
            logger.debug(f"Health check error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
