"""Inspector view-model helpers: server-id encoding + overview builder."""

import asyncio
import logging
from typing import Any

from .proxy import InspectorProxy, InspectorProxyError

logger = logging.getLogger(__name__)


def make_server_id(location: str, name: str, runner: str | None = None) -> str:
    """Construct a canonical ``server_id``.

    ``location`` is one of ``control_plane`` | ``runner:<name>`` | ``native``.
    Callers should prefer this helper rather than string-formatting ad hoc.
    """
    if location == "control_plane":
        return f"cp::{name}"
    if location == "native":
        return f"native::{name}"
    if location.startswith("runner:"):
        if not runner:
            runner = location.split(":", 1)[1]
        return f"runner:{runner}::{name}"
    raise ValueError(f"Unknown location: {location}")


async def _safe(coro: Any, default: Any) -> Any:
    try:
        return await coro
    except InspectorProxyError as e:
        logger.warning(f"[inspector] overview fetch failed: {e}")
        return default


async def build_overview(proxy: InspectorProxy) -> dict[str, Any]:
    """Compose the full overview payload used by the SPA on first paint."""
    capabilities, health, config_tools, runners_list = await asyncio.gather(
        _safe(proxy.get_capabilities(), {}),
        _safe(proxy.health(), {}),
        _safe(proxy.get_config(section="tools"), {"tools": {}}),
        _safe(proxy.list_runners(), []),
    )

    tools_cfg = config_tools.get("tools", {}) or {}
    cp_mcp_servers: dict[str, Any] = tools_cfg.get("mcp_servers", {}) or {}

    cp_meta = {
        "url": proxy.url,
        "version": capabilities.get("version"),
        "tier": capabilities.get("tier"),
        "connected": bool(health),
    }

    servers: list[dict[str, Any]] = []

    # CP-hosted MCP servers
    for name, server_cfg in cp_mcp_servers.items():
        cp_status = await _safe(proxy.get_cp_mcp_status(name), {})
        servers.append(
            {
                "id": make_server_id("control_plane", name),
                "location": "control_plane",
                "name": name,
                "transport": server_cfg.get("transport", "stdio"),
                "command": server_cfg.get("command"),
                "status": cp_status.get("status", "unknown"),
                "tool_count": cp_status.get("tool_count", 0),
                "last_connected_at": cp_status.get("last_connected_at"),
                "tags": ["source:mcp", f"server:{name}"],
            }
        )

    # Runner-hosted MCP servers
    for runner_summary in runners_list:
        runner_name = runner_summary.get("name")
        if not runner_name:
            continue
        runner_detail = await _safe(proxy.get_runner(runner_name), {})
        mcps = runner_detail.get("mcps", []) or runner_detail.get("mcp_servers", []) or []
        for mcp in mcps:
            mcp_name = mcp if isinstance(mcp, str) else mcp.get("name", "")
            if not mcp_name:
                continue
            mcp_status = await _safe(proxy.get_runner_mcp_status(runner_name, mcp_name), {})
            servers.append(
                {
                    "id": make_server_id(f"runner:{runner_name}", mcp_name, runner=runner_name),
                    "location": f"runner:{runner_name}",
                    "name": mcp_name,
                    "transport": (mcp.get("transport") if isinstance(mcp, dict) else None)
                    or "stdio",
                    "command": mcp.get("command") if isinstance(mcp, dict) else None,
                    "status": mcp_status.get("status", "unknown"),
                    "tool_count": 0,
                    "last_connected_at": None,
                    "tags": ["source:mcp", f"server:{mcp_name}", f"runner:{runner_name}"],
                }
            )

    # Tools
    tools = await _safe(proxy.list_tools(), [])
    tool_rows: list[dict[str, Any]] = []
    for tool in tools:
        source = tool.get("source", "mcp")
        server_name = tool.get("server")
        if source == "native":
            server_id = make_server_id("native", server_name or "native")
        elif source == "runner" and server_name:
            server_id = make_server_id(f"runner:{server_name}", server_name, runner=server_name)
        elif server_name:
            server_id = make_server_id("control_plane", server_name)
        else:
            server_id = make_server_id("native", tool.get("name", ""))

        tool_rows.append(
            {
                "name": tool.get("name"),
                "server_id": server_id,
                "description": tool.get("description", ""),
                "input_schema": tool.get("input_schema", {}),
                "output_schema": tool.get("output_schema"),
                "tags": tool.get("tags", []),
                "status": tool.get("status", "available"),
            }
        )

    # Native "servers" entry if any native tools exist and we haven't added one
    native_tools = [t for t in tools if t.get("source") == "native"]
    if native_tools and not any(s["location"] == "native" for s in servers):
        servers.append(
            {
                "id": make_server_id("native", "native-tools"),
                "location": "native",
                "name": "native-tools",
                "transport": "in-process",
                "command": None,
                "status": "connected",
                "tool_count": len(native_tools),
                "last_connected_at": None,
                "tags": ["source:native"],
            }
        )

    return {
        "cp": cp_meta,
        "servers": servers,
        "tools": tool_rows,
    }
