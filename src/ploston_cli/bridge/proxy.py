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
            url: Control Plane URL (e.g., http://localhost:8022)
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

        # Bridge context propagation (DEC-142, DEC-157).
        # Set by BridgeLifecycle after construction.
        self.bridge_id: str | None = None
        self.bridge_expose: str | None = None
        self.bridge_session_start: str | None = None
        self.bridge_runner: str | None = None  # DEC-157: runner name for tool resolution
        self._lifecycle: Any | None = None  # back-ref for queue drops

    def set_lifecycle(self, lifecycle: Any) -> None:
        """Attach lifecycle for bridge context propagation."""
        self._lifecycle = lifecycle
        self.bridge_id = lifecycle.bridge_id
        self.bridge_session_start = lifecycle.session_start

    def _get_headers(self) -> dict[str, str]:
        """Get HTTP headers including auth and bridge context."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        # Bridge context headers (DEC-142)
        if self.bridge_id:
            headers["X-Bridge-ID"] = self.bridge_id
        if self.bridge_expose:
            headers["X-Bridge-Expose"] = self.bridge_expose
        if self._lifecycle:
            headers["X-Bridge-Queue-Drops"] = str(self._lifecycle._queue_drops_since_connect)
        if self.bridge_session_start:
            headers["X-Bridge-Session-Start"] = self.bridge_session_start
        # DEC-157: Runner name for workflow tool resolution
        if self.bridge_runner:
            headers["X-Bridge-Runner"] = self.bridge_runner
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

        method = request.get("method", "unknown")
        request_id = request.get("id", "notification")
        logger.debug(f"HTTP POST {url} - method={method} id={request_id}")

        try:
            response = await client.post(url, json=request)

            logger.debug(
                f"HTTP response: status={response.status_code} "
                f"content-type={response.headers.get('content-type', 'unknown')}"
            )

            if response.status_code == 401 or response.status_code == 403:
                error = map_http_error(response.status_code, response.text)
                logger.debug(f"HTTP auth error: {error.code} - {error.message}")
                raise BridgeProxyError(
                    code=error.code,
                    message=error.message,
                    retryable=error.retryable,
                    data=error.data,
                )

            if response.status_code >= 400:
                error = map_http_error(response.status_code, response.text)
                logger.debug(f"HTTP error: {error.code} - {error.message}")
                raise BridgeProxyError(
                    code=error.code,
                    message=error.message,
                    retryable=error.retryable,
                    data=error.data,
                )

            result = response.json()

            # Log response summary
            if "error" in result:
                err = result["error"]
                logger.debug(f"CP returned error: {err.get('code')} - {err.get('message')}")
            else:
                inner = result.get("result", {})
                # Surface non-standard MCP fields (e.g. _meta, structuredContent)
                # so they are never silently lost to log truncation.
                # Only applies to tool-call-shaped results (those with a "content" key).
                _standard_keys = {"content", "isError"}
                mcp_extra = (
                    {k: v for k, v in inner.items() if k not in _standard_keys}
                    if isinstance(inner, dict) and "content" in inner
                    else None
                ) or None
                extra_suffix = f" mcp_extra={json.dumps(mcp_extra)}" if mcp_extra else ""

                # Truncate large results for logging
                result_preview = json.dumps(inner)
                if len(result_preview) > 300:
                    result_preview = result_preview[:300] + "..."
                logger.debug(f"CP returned result: {result_preview}{extra_suffix}")

            return result

        except httpx.ConnectError as e:
            error = map_connection_error(str(e), url)
            logger.debug(f"HTTP connection error: {e}")
            raise BridgeProxyError(
                code=error.code,
                message=f"Cannot reach Control Plane at {self.url}: {e}",
                retryable=True,
            ) from e
        except httpx.TimeoutException as e:
            error = map_connection_error(str(e), url, is_timeout=True)
            logger.debug(f"HTTP timeout: {e}")
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

    async def get_mcp_status(self, runner_name: str, mcp_name: str) -> dict[str, Any]:
        """Query CP for the status of a single MCP on a runner.

        Calls ``GET /api/v1/runners/{runner}/mcps/{mcp}/status``.

        Returns:
            Status dict with ``mcp_name``, ``status``, ``error`` (if any).

        Raises:
            BridgeProxyError: On connection or HTTP error
        """
        client = await self._ensure_client()
        url = f"{self.url}/api/v1/runners/{runner_name}/mcps/{mcp_name}/status"

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
