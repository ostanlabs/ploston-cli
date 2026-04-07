"""BridgeServer - Stdio MCP server facing agents.

Handles stdio MCP protocol from agents (Claude Desktop, Cursor, etc.)
and forwards requests to Control Plane via BridgeProxy.
"""

import logging
from typing import Any, Callable

from .errors import (
    BRIDGE_EMPTY_TOOLS_ERROR,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_SERVER_ERROR,
    ExposeAmbiguityError,
)
from .proxy import BridgeProxy, BridgeProxyError

logger = logging.getLogger(__name__)

# Bridge version
BRIDGE_VERSION = "1.0.0"

# Legacy --expose / --tools sugar → tag expressions.
# Each key resolves to a list of tag-sets.  Multiple tag-sets are OR-ed;
# tags within a single set are AND-ed (match-all semantics on CP side).
_EXPOSE_SUGAR: dict[str, list[set[str]]] = {
    "all": [],  # empty → no filter
    "workflows": [{"kind:workflow"}],
    "local": [{"source:runner"}],
    "native": [{"source:native"}],
    "authoring": [{"kind:workflow_mgmt"}],
}

# Keep the old class attribute name for backward compat in tests that
# reference BridgeServer.TOOLS_FILTER_MAP.  Values are now tag-sets.
_TOOLS_FILTER_SUGAR: dict[str, list[set[str]]] = {
    "all": [],
    "local": [{"source:runner"}],
    "native": [{"source:native"}],
}


def resolve_expose_flags(
    flags: list[str],
    tools_filter: str = "all",
) -> list[set[str]] | None:
    """Resolve ``--expose`` flag values + legacy ``--tools`` into tag-sets.

    Returns a list of tag-sets (OR across sets, AND within each set),
    or ``None`` when no filtering is requested.

    Flag resolution rules (per §2.5):
      * ``"workflows"``     → ``{kind:workflow}``
      * ``"all"``           → no filter
      * ``"local"``         → ``{source:runner}``
      * ``"native"``        → ``{source:native}``
      * ``"authoring"``     → ``{kind:workflow_mgmt}``
      * ``"tag:<expr>"``    → direct tag match (space-separated tags AND-ed)
      * ``<server_name>``   → ``{server:<server_name>}``

    Multiple flags are combined with OR across the top-level values.
    """
    # Legacy --tools path
    if not flags:
        tag_sets = _TOOLS_FILTER_SUGAR.get(tools_filter, [])
        return tag_sets if tag_sets else None

    result: list[set[str]] = []
    for flag in flags:
        # Check sugar table first
        if flag in _EXPOSE_SUGAR:
            sugar = _EXPOSE_SUGAR[flag]
            if not sugar:
                # "all" → no filter
                return None
            result.extend(sugar)
        elif flag.startswith("tag:"):
            # Direct tag expression: "tag:kind:workflow tag:kind:workflow_mgmt"
            # or "tag:kind:workflow" (single)
            raw = flag[4:]  # strip "tag:" prefix
            # Space-separated tags within a single flag are AND-ed
            tags = {t.strip() for t in raw.split() if t.strip()}
            if tags:
                result.append(tags)
        else:
            # Assume server name → server:<name>
            result.append({f"server:{flag}"})

    return result if result else None


class BridgeServer:
    """Stdio MCP server that bridges to Control Plane.

    Receives JSON-RPC requests on stdin, forwards to CP via BridgeProxy,
    and returns responses on stdout.
    """

    # Backward compat: kept as class attribute so existing tests that reference
    # BridgeServer.TOOLS_FILTER_MAP continue to import without error.
    TOOLS_FILTER_MAP = {
        "all": None,
        "local": ["runner"],
        "native": ["native"],
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
            expose: Inline tool filter — MCP server name, tag expression, or
                    legacy sugar ("workflows", "authoring", etc.)
            runner: Runner name for disambiguation when --expose targets a runner-hosted server
        """
        self.proxy = proxy
        self.tools_filter = tools_filter
        self.expose = expose
        self.runner = runner
        self.on_notification: Callable[[dict[str, Any]], None] | None = None
        self._cp_server_info: dict[str, Any] | None = None
        self._session_map: dict[str, str] = {}  # clean_name → canonical_name
        self.shutdown_requested: bool = False

        # Resolve flags once at construction time.
        expose_flags = [expose] if expose else []
        self._resolved_tag_sets = resolve_expose_flags(expose_flags, tools_filter)
        # Detect whether this bridge exposes a specific runner-hosted server
        # (needs session-map / prefix-stripping behavior).
        self._is_server_expose = (
            expose is not None and expose not in _EXPOSE_SUGAR and not expose.startswith("tag:")
        )

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
        """Handle tools/list request — forward tags to CP and apply server-expose logic.

        Tag-based filtering (§2.5):
          * ``_resolved_tag_sets`` is forwarded as ``params.tags`` so the CP
            does the heavy filtering and strips ``_ploston_tags``.
          * Server-expose (``--expose <server_name>``) still uses local
            three-part prefix matching + session-map logic because the CP
            returns runner tools with ``runner__mcp__tool`` names and the
            bridge must strip the prefix and maintain a reverse map.
        """
        request_id = request.get("id")

        # Build forwarded request with tags when applicable
        forwarded = request.copy()
        params = (forwarded.get("params") or {}).copy()

        if self._resolved_tag_sets and not self._is_server_expose:
            # Flatten tag-sets into a list of tag strings for CP.
            # CP `_handle_tools_list` already accepts `tags` param (S-242).
            flat_tags = sorted({t for ts in self._resolved_tag_sets for t in ts})
            params["tags"] = flat_tags

        forwarded["params"] = params
        cp_response = await self._forward_request(forwarded)

        # Server-expose still needs local prefix matching + stripping
        if self._is_server_expose:
            all_tools = cp_response.get("result", {}).get("tools", [])
            filtered_tools = self._filter_by_expose(all_tools, self.expose, self.runner)
            self._session_map = self._build_session_map(filtered_tools)
            filtered_tools = [self._strip_prefix(t) for t in filtered_tools]
            tool_count = len(filtered_tools)
            if tool_count == 0:
                msg = (
                    f"Bridge has 0 tools for expose='{self.expose}' "
                    f"runner='{self.runner}' (CP returned {len(all_tools)} total). "
                    f"The MCP server may not be configured on the runner, or all "
                    f"tools were de-registered. Bridge will shut down."
                )
                logger.error(f"[bridge] {msg}")
                self.shutdown_requested = True
                return self._make_error_response(request_id, BRIDGE_EMPTY_TOOLS_ERROR, msg)
            logger.info(
                f"[bridge] tools/list: {tool_count} tools exposed "
                f"(expose='{self.expose}' runner='{self.runner}')"
            )
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": filtered_tools},
            }

        # For tag-based paths the CP already did the filtering; return as-is.
        tag_tools = cp_response.get("result", {}).get("tools", [])
        if len(tag_tools) == 0 and self._resolved_tag_sets:
            msg = (
                f"Bridge has 0 tools for tags={self._resolved_tag_sets}. "
                f"No tools match the requested filter. Bridge will shut down."
            )
            logger.error(f"[bridge] {msg}")
            self.shutdown_requested = True
            return self._make_error_response(request_id, BRIDGE_EMPTY_TOOLS_ERROR, msg)
        logger.info(
            f"[bridge] tools/list: {len(tag_tools)} tools returned (tags={self._resolved_tag_sets})"
        )
        return cp_response

    async def _handle_tools_call(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call request - reverse-resolve exposed names and forward to CP."""
        request_id = request.get("id")
        params = request.get("params", {})
        tool_name = params.get("name", "")

        if self._is_server_expose:
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
