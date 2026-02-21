"""BridgeProxy - HTTP+SSE MCP client connecting to Control Plane.

Handles HTTP transport for MCP protocol:
- POST /mcp for JSON-RPC requests
- GET /mcp/sse for server-sent events (notifications)
- GET /health for health checks
"""

import asyncio
import json
import logging
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx
from httpx_sse import aconnect_sse

from .errors import BridgeError, map_connection_error, map_http_error

logger = logging.getLogger(__name__)


class BridgeProxyError(BridgeError):
    """Error raised by BridgeProxy operations."""

    pass


class BridgeProxy:
    """HTTP+SSE MCP client for connecting to Control Plane.

    Translates MCP JSON-RPC requests to HTTP POST /mcp and handles
    SSE notifications from GET /mcp/sse.
    """

    def __init__(
        self,
        url: str,
        token: str | None = None,
        timeout: float = 30.0,
        insecure: bool = False,
    ):
        """Initialize BridgeProxy.

        Args:
            url: Control Plane URL (e.g., http://localhost:8080)
            token: Optional bearer token for authentication
            timeout: Request timeout in seconds (default: 30)
            insecure: Skip SSL certificate verification (default: False)

        Raises:
            ValueError: If URL is invalid
        """
        # Validate URL
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid URL: {url}")

        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.insecure = insecure
        self._client: httpx.AsyncClient | None = None
        self._closed = False
        self._request_id = 0

    def _get_headers(self) -> dict[str, str]:
        """Get HTTP headers including auth if configured."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure HTTP client is initialized."""
        if self._closed:
            raise BridgeProxyError(
                code=-32000,
                message="BridgeProxy is closed",
            )
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers=self._get_headers(),
                verify=not self.insecure,
            )
        return self._client

    async def initialize(self) -> dict[str, Any]:
        """Send MCP initialize request to CP.

        Returns:
            Initialize result with protocolVersion, capabilities, serverInfo

        Raises:
            BridgeProxyError: On connection or protocol error
        """
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ploston-bridge", "version": "1.0.0"},
            },
        }

        response = await self.send_request(request)

        if "error" in response:
            error = response["error"]
            raise BridgeProxyError(
                code=error.get("code", -32000),
                message=error.get("message", "Initialize failed"),
            )

        return response.get("result", {})

    async def send_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send JSON-RPC request to CP via POST /mcp.

        Args:
            request: JSON-RPC request object

        Returns:
            JSON-RPC response object

        Raises:
            BridgeProxyError: On connection or HTTP error
        """
        client = await self._ensure_client()
        url = f"{self.url}/mcp"

        try:
            response = await client.post(url, json=request)

            if response.status_code == 401 or response.status_code == 403:
                error = map_http_error(response.status_code, response.text)
                raise BridgeProxyError(
                    code=error.code,
                    message=error.message,
                    retryable=error.retryable,
                    data=error.data,
                )

            if response.status_code >= 400:
                error = map_http_error(response.status_code, response.text)
                raise BridgeProxyError(
                    code=error.code,
                    message=error.message,
                    retryable=error.retryable,
                    data=error.data,
                )

            return response.json()

        except httpx.ConnectError as e:
            error = map_connection_error(str(e), url)
            raise BridgeProxyError(
                code=error.code,
                message=f"Cannot reach Control Plane at {self.url}: {e}",
                retryable=True,
            ) from e
        except httpx.TimeoutException as e:
            error = map_connection_error(str(e), url, is_timeout=True)
            raise BridgeProxyError(
                code=error.code,
                message=error.message,
                retryable=True,
            ) from e

    async def subscribe_notifications(
        self,
        max_reconnect_attempts: int = 3,
        reconnect_delay: float = 1.0,
    ) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to SSE notifications from CP with auto-reconnect.

        Args:
            max_reconnect_attempts: Maximum reconnection attempts (default: 3)
            reconnect_delay: Initial delay between reconnects in seconds (default: 1.0)

        Yields:
            Parsed notification events from GET /mcp/sse

        Raises:
            BridgeProxyError: On connection error after all retries exhausted
        """
        url = f"{self.url}/mcp/sse"
        reconnect_attempts = 0

        while True:
            client = await self._ensure_client()

            try:
                async with aconnect_sse(client, "GET", url) as event_source:
                    # Reset reconnect counter on successful connection
                    reconnect_attempts = 0
                    logger.info(f"SSE connected to {url}")

                    async for sse in event_source.aiter_sse():
                        if sse.data:
                            try:
                                event = json.loads(sse.data)
                                yield event
                            except json.JSONDecodeError:
                                logger.warning(f"Invalid JSON in SSE event: {sse.data}")

            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as e:
                reconnect_attempts += 1
                logger.warning(
                    f"SSE connection dropped (attempt {reconnect_attempts}/{max_reconnect_attempts}): {e}"
                )

                if reconnect_attempts >= max_reconnect_attempts:
                    error = map_connection_error(str(e), url)
                    raise BridgeProxyError(
                        code=error.code,
                        message=f"SSE connection failed after {max_reconnect_attempts} attempts: {e}",
                        retryable=True,
                    ) from e

                # Exponential backoff
                delay = reconnect_delay * (2 ** (reconnect_attempts - 1))
                logger.info(f"Reconnecting SSE in {delay}s...")
                await asyncio.sleep(delay)

    async def health_check(self) -> dict[str, Any]:
        """Check CP health via GET /health.

        Returns:
            Health status response

        Raises:
            BridgeProxyError: On connection or HTTP error
        """
        client = await self._ensure_client()
        url = f"{self.url}/health"

        try:
            response = await client.get(url)
            if response.status_code >= 400:
                error = map_http_error(response.status_code, response.text)
                raise BridgeProxyError(
                    code=error.code,
                    message=error.message,
                    retryable=error.retryable,
                )
            return response.json()
        except httpx.ConnectError as e:
            error = map_connection_error(str(e), url)
            raise BridgeProxyError(
                code=error.code,
                message=error.message,
                retryable=True,
            ) from e

    async def close(self) -> None:
        """Close HTTP client and release resources."""
        self._closed = True
        if self._client:
            await self._client.aclose()
            self._client = None
