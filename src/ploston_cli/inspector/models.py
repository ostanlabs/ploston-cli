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


# Keys surfaced in the "config" pane. Anything outside this allow-list is dropped
# to avoid leaking unrelated runner/CP state into the UI.
_CONFIG_KEYS = ("transport", "command", "args", "url", "env", "cwd", "headers")


def _normalize_mcp_config(cfg: Any) -> dict[str, Any]:
    """Build the serializable config blob for one MCP server entry.

    Accepts either a dict (real shape) or anything else (which yields ``{}``).
    Only whitelisted keys are kept; values are passed through unchanged so the
    SPA can render args/env/cwd verbatim.
    """
    if not isinstance(cfg, dict):
        return {}
    return {k: cfg[k] for k in _CONFIG_KEYS if k in cfg}


def _iter_runner_mcps(raw: Any):
    """Yield ``(name, config_dict)`` tuples for a runner's MCP list.

    Tolerates:
      - dict keyed by name → config (production shape)
      - list of dicts each with a ``name`` key (legacy/test shape)
      - list of bare strings (names only, no config)
    """
    if isinstance(raw, dict):
        for name, cfg in raw.items():
            yield name, cfg if isinstance(cfg, dict) else {}
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                yield item, {}
            elif isinstance(item, dict):
                yield item.get("name", ""), item


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
                "config": _normalize_mcp_config(server_cfg),
            }
        )

    # Runner-hosted MCP servers.
    # CP returns ``mcps`` as a dict (name -> config) but the legacy/test shape
    # was a list of dicts each with a "name" key — accept both.
    for runner_summary in runners_list:
        runner_name = runner_summary.get("name")
        if not runner_name:
            continue
        runner_detail = await _safe(proxy.get_runner(runner_name), {})
        raw_mcps = runner_detail.get("mcps") or runner_detail.get("mcp_servers") or {}
        for mcp_name, mcp_cfg in _iter_runner_mcps(raw_mcps):
            if not mcp_name:
                continue
            mcp_status = await _safe(proxy.get_runner_mcp_status(runner_name, mcp_name), {})
            servers.append(
                {
                    "id": make_server_id(f"runner:{runner_name}", mcp_name, runner=runner_name),
                    "location": f"runner:{runner_name}",
                    "name": mcp_name,
                    "transport": mcp_cfg.get("transport") or "stdio",
                    "command": mcp_cfg.get("command"),
                    "status": mcp_status.get("status", "unknown"),
                    "tool_count": 0,
                    "last_connected_at": None,
                    "tags": ["source:mcp", f"server:{mcp_name}", f"runner:{runner_name}"],
                    "config": _normalize_mcp_config(mcp_cfg),
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
                "config": {"transport": "in-process"},
            }
        )

    return {
        "cp": cp_meta,
        "servers": servers,
        "tools": tool_rows,
    }
