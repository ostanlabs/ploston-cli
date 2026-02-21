"""BridgeServer - Stdio MCP server facing agents.

Handles stdio MCP protocol from agents (Claude Desktop, Cursor, etc.)
and forwards requests to Control Plane via BridgeProxy.
"""

import logging
from typing import Any, Callable

from .errors import JSONRPC_SERVER_ERROR
from .proxy import BridgeProxy, BridgeProxyError

logger = logging.getLogger(__name__)

# Bridge version
BRIDGE_VERSION = "1.0.0"


class BridgeServer:
    """Stdio MCP server that bridges to Control Plane.

    Receives JSON-RPC requests on stdin, forwards to CP via BridgeProxy,
    and returns responses on stdout.
    """

    def __init__(self, proxy: BridgeProxy):
        """Initialize BridgeServer.

        Args:
            proxy: BridgeProxy instance for CP communication
        """
        self.proxy = proxy
        self.on_notification: Callable[[dict[str, Any]], None] | None = None
        self._cp_server_info: dict[str, Any] | None = None

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Handle incoming JSON-RPC request from agent.

        Args:
            request: JSON-RPC request object

        Returns:
            JSON-RPC response object, or None for notifications (no id)
        """
        method = request.get("method", "")
        request_id = request.get("id")

        # JSON-RPC notifications have no id and should not receive a response
        # Per spec: "A Notification is a Request object without an 'id' member"
        is_notification = "id" not in request

        try:
            if method == "initialize":
                return await self._handle_initialize(request)
            elif method == "tools/list":
                return await self._handle_tools_list(request)
            elif method == "tools/call":
                return await self._handle_tools_call(request)
            elif is_notification:
                # Notifications don't get responses - just log and return None
                logger.debug(f"Received notification: {method}")
                return None
            else:
                # Forward unknown methods to CP
                return await self._forward_request(request)
        except BridgeProxyError as e:
            if is_notification:
                logger.warning(f"Error handling notification {method}: {e.message}")
                return None
            return self._make_error_response(request_id, e.code, e.message)
        except Exception as e:
            if is_notification:
                logger.warning(f"Error handling notification {method}: {e}")
                return None
            logger.exception(f"Error handling request: {e}")
            return self._make_error_response(
                request_id, JSONRPC_SERVER_ERROR, f"Internal bridge error: {e}"
            )

    async def _handle_initialize(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle initialize request - forward to CP and enrich response."""
        request_id = request.get("id")

        # Forward to CP
        cp_result = await self.proxy.initialize()
        self._cp_server_info = cp_result.get("serverInfo", {})

        # Enrich with bridge metadata
        result = {
            "protocolVersion": cp_result.get("protocolVersion", "2024-11-05"),
            "capabilities": cp_result.get("capabilities", {}),
            "serverInfo": {
                "name": "ploston-bridge",
                "version": BRIDGE_VERSION,
                "cpServerInfo": self._cp_server_info,
            },
        }

        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    async def _handle_tools_list(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/list request - forward to CP and return as-is."""
        return await self._forward_request(request)

    async def _handle_tools_call(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call request - forward to CP and return result."""
        return await self._forward_request(request)

    async def _forward_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Forward request to CP via proxy."""
        return await self.proxy.send_request(request)

    async def handle_cp_notification(self, notification: dict[str, Any]) -> None:
        """Handle notification from CP (via SSE).

        Args:
            notification: JSON-RPC notification from CP
        """
        if self.on_notification:
            self.on_notification(notification)

    def _make_error_response(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        """Create JSON-RPC error response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
