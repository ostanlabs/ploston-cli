"""BridgeServer - Stdio MCP server facing agents.

Handles stdio MCP protocol from agents (Claude Desktop, Cursor, etc.)
and forwards requests to Control Plane via BridgeProxy.
"""

import logging
from typing import Any, Callable

from .errors import JSONRPC_INVALID_REQUEST, JSONRPC_SERVER_ERROR, ExposeAmbiguityError
from .proxy import BridgeProxy, BridgeProxyError

logger = logging.getLogger(__name__)

# Bridge version
BRIDGE_VERSION = "1.0.0"


class BridgeServer:
    """Stdio MCP server that bridges to Control Plane.

    Receives JSON-RPC requests on stdin, forwards to CP via BridgeProxy,
    and returns responses on stdout.
    """

    # Map tools filter to source list for CP
    TOOLS_FILTER_MAP = {
        "all": None,  # No filter - return all tools
        "local": ["runner"],  # Only runner tools
        "native": ["native"],  # Only native tools
    }

    def __init__(
        self,
        proxy: BridgeProxy,
        tools_filter: str = "all",
        expose: str | None = None,
        runner: str | None = None,
    ):
        """Initialize BridgeServer.

        Args:
            proxy: BridgeProxy instance for CP communication
            tools_filter: Which tools to expose: "all", "local", or "native"
            expose: Inline tool filter — MCP server name or "workflows"
            runner: Runner name for disambiguation when --expose targets a runner-hosted server
        """
        self.proxy = proxy
        self.tools_filter = tools_filter
        self.expose = expose
        self.runner = runner
        self.on_notification: Callable[[dict[str, Any]], None] | None = None
        self._cp_server_info: dict[str, Any] | None = None
        self._session_map: dict[str, str] = {}  # clean_name → canonical_name

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Handle incoming JSON-RPC request from agent.

        Args:
            request: JSON-RPC request object

        Returns:
            JSON-RPC response object, or None for notifications (no id)
        """
        method = request.get("method", "")
        request_id = request.get("id")
        params = request.get("params", {})

        # JSON-RPC notifications have no id and should not receive a response
        # Per spec: "A Notification is a Request object without an 'id' member"
        is_notification = "id" not in request

        logger.debug(
            f"Handling request: method={method} id={request_id} notification={is_notification}"
        )

        try:
            if method == "initialize":
                logger.debug("Handling initialize request")
                return await self._handle_initialize(request)
            elif method == "tools/list":
                logger.debug("Handling tools/list request")
                return await self._handle_tools_list(request)
            elif method == "tools/call":
                tool_name = params.get("name", "unknown")
                logger.debug(f"Handling tools/call request: tool={tool_name}")
                return await self._handle_tools_call(request)
            elif is_notification:
                # Notifications don't get responses - just log and return None
                logger.debug(f"Received notification: {method}")
                return None
            else:
                # Forward unknown methods to CP
                logger.debug(f"Forwarding unknown method to CP: {method}")
                return await self._forward_request(request)
        except BridgeProxyError as e:
            logger.debug(f"BridgeProxyError: code={e.code} message={e.message}")
            if is_notification:
                logger.warning(f"Error handling notification {method}: {e.message}")
                return None
            return self._make_error_response(request_id, e.code, e.message)
        except ExposeAmbiguityError as e:
            logger.warning(f"Expose ambiguity: {e.message}")
            if is_notification:
                return None
            return self._make_error_response(request_id, e.code, e.message)
        except Exception as e:
            logger.debug(f"Unexpected error: {type(e).__name__}: {e}")
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
        """Handle tools/list request - forward to CP with optional source/expose filter."""
        request_id = request.get("id")

        # Add source filter to params if configured (--tools flag)
        sources = self.TOOLS_FILTER_MAP.get(self.tools_filter)
        if sources is not None:
            filtered_request = request.copy()
            params = filtered_request.get("params", {}) or {}
            params = params.copy()
            params["sources"] = sources
            filtered_request["params"] = params
            cp_response = await self._forward_request(filtered_request)
        else:
            cp_response = await self._forward_request(request)

        # If no --expose, return CP response unchanged
        if not self.expose:
            return cp_response

        # Extract tools from CP response
        all_tools = cp_response.get("result", {}).get("tools", [])

        if self.expose == "workflows":
            filtered_tools = [
                t
                for t in all_tools
                if t["name"].startswith("workflow_") or t["name"] == "ploston:workflow_schema"
            ]
        else:
            # --expose <server_name>: filter runner tools + strip prefix
            filtered_tools = self._filter_by_expose(all_tools, self.expose, self.runner)
            self._session_map = self._build_session_map(filtered_tools)
            filtered_tools = [self._strip_prefix(t) for t in filtered_tools]

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": filtered_tools},
        }

    async def _handle_tools_call(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call request - reverse-resolve exposed names and forward to CP."""
        request_id = request.get("id")
        params = request.get("params", {})
        tool_name = params.get("name", "")

        if self.expose and self.expose != "workflows":
            canonical = self._session_map.get(tool_name)
            if canonical is None:
                return self._make_error_response(
                    request_id,
                    JSONRPC_INVALID_REQUEST,
                    f"Tool '{tool_name}' not available in this bridge (exposed: {self.expose}).",
                )
            # Replace tool name with canonical name for CP
            resolved_request = request.copy()
            resolved_params = params.copy()
            resolved_params["name"] = canonical
            resolved_request["params"] = resolved_params
            return await self._forward_request(resolved_request)

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

    def _filter_by_expose(
        self,
        tools: list[dict[str, Any]],
        server_name: str,
        runner_name: str | None,
    ) -> list[dict[str, Any]]:
        """Filter to runner tools whose mcp segment matches server_name.

        Only runner tools have the 3-part prefix runner__mcp__tool.
        CP-direct MCP, NATIVE, SYSTEM, and workflow tools have no __ separator
        and are never matched — correct and complete by design.
        """

        def parse(name: str) -> tuple[str, str, str] | None:
            parts = name.split("__", 2)
            return tuple(parts) if len(parts) == 3 else None  # type: ignore[return-value]

        matched = [t for t in tools if (p := parse(t["name"])) and p[1] == server_name]

        if runner_name:
            matched = [t for t in matched if t["name"].startswith(f"{runner_name}__")]
        else:
            runners = {t["name"].split("__")[0] for t in matched}
            if len(runners) > 1:
                raise ExposeAmbiguityError(
                    message=(
                        f"Server '{server_name}' found on multiple runners: {sorted(runners)}. "
                        f"Add --runner to disambiguate."
                    ),
                )
            if len(runners) == 1:
                logger.warning(
                    f"--runner not specified; inferred runner '{list(runners)[0]}' "
                    f"for --expose {server_name}. Recommend adding --runner explicitly."
                )

        return matched

    def _strip_prefix(self, tool: dict[str, Any]) -> dict[str, Any]:
        """Strip runner__mcp__ prefix, returning tool_name only."""
        parts = tool["name"].split("__", 2)
        if len(parts) == 3:
            return {**tool, "name": parts[2]}
        return tool

    def _build_session_map(self, tools: list[dict[str, Any]]) -> dict[str, str]:
        """Build reverse map: clean_name → canonical_name."""
        result: dict[str, str] = {}
        for tool in tools:
            parts = tool["name"].split("__", 2)
            if len(parts) == 3:
                result[parts[2]] = tool["name"]
        return result

    def _make_error_response(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        """Create JSON-RPC error response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
