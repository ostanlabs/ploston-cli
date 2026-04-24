"""Tests for inspector overview builder + server_id helpers."""

from unittest.mock import AsyncMock

import pytest

from ploston_cli.inspector import models
from ploston_cli.inspector.models import build_overview, make_server_id


def test_make_server_id_cp():
    assert make_server_id("control_plane", "fs") == "cp::fs"


def test_make_server_id_native():
    assert make_server_id("native", "clock") == "native::clock"


def test_make_server_id_runner():
    assert make_server_id("runner:host-a", "slack", runner="host-a") == "runner:host-a::slack"


def test_make_server_id_rejects_unknown_location():
    with pytest.raises(ValueError):
        make_server_id("mystery", "x")


def _mk_proxy():
    proxy = AsyncMock()
    proxy.url = "http://cp:8022"
    proxy.get_capabilities.return_value = {"version": "1.0", "tier": "full"}
    proxy.health.return_value = {"status": "ok"}
    proxy.get_config.return_value = {
        "tools": {
            "mcp_servers": {
                "filesystem": {"transport": "stdio", "command": "/bin/fs"},
            }
        }
    }
    proxy.list_runners.return_value = [{"name": "runner-a"}]
    proxy.get_runner.return_value = {
        "mcps": [{"name": "slack", "transport": "stdio", "command": "/bin/slack"}]
    }
    proxy.get_cp_mcp_status.return_value = {
        "status": "connected",
        "tool_count": 3,
        "last_connected_at": "2026-04-23T10:00:00Z",
    }
    proxy.get_runner_mcp_status.return_value = {
        "status": "connected",
        "tool_count": 2,
    }
    proxy.list_tools.return_value = [
        {
            "name": "read_file",
            "source": "mcp",
            "server": "filesystem",
            "description": "Reads files",
            "tags": [],
        },
        # Runner-surfaced tools carry the "<mcp>__" prefix so the inspector
        # can map them back to the correct MCP server bucket.
        {
            "name": "slack__post_message",
            "source": "runner",
            "server": "runner-a",
            "description": "Posts to Slack",
            "tags": [],
        },
        {"name": "now", "source": "native", "description": "Clock", "tags": []},
    ]
    return proxy


@pytest.mark.asyncio
async def test_build_overview_has_cp_meta():
    proxy = _mk_proxy()
    result = await build_overview(proxy)
    assert result["cp"]["url"] == "http://cp:8022"
    assert result["cp"]["version"] == "1.0"
    assert result["cp"]["connected"] is True


@pytest.mark.asyncio
async def test_build_overview_includes_cp_server():
    proxy = _mk_proxy()
    result = await build_overview(proxy)
    cp_servers = [s for s in result["servers"] if s["location"] == "control_plane"]
    assert len(cp_servers) == 1
    assert cp_servers[0]["id"] == "cp::filesystem"
    # tool_count is re-derived from routed tools (matches what the tree shows)
    assert cp_servers[0]["tool_count"] == 1
    assert cp_servers[0]["status"] == "connected"


@pytest.mark.asyncio
async def test_build_overview_includes_runner_server():
    proxy = _mk_proxy()
    result = await build_overview(proxy)
    runner_servers = [s for s in result["servers"] if s["location"].startswith("runner:")]
    # One real MCP (slack) declared on runner-a; no inline tools, so no
    # synthesized catch-all entry.
    real = [s for s in runner_servers if not s["name"].endswith("(inline)")]
    assert len(real) == 1
    assert real[0]["id"] == "runner:runner-a::slack"
    assert real[0]["tool_count"] == 1  # slack__post_message routed here


@pytest.mark.asyncio
async def test_build_overview_synthesizes_native_server_entry():
    proxy = _mk_proxy()
    result = await build_overview(proxy)
    native_servers = [s for s in result["servers"] if s["location"] == "native"]
    assert len(native_servers) == 1
    assert native_servers[0]["tool_count"] == 1


@pytest.mark.asyncio
async def test_build_overview_tools_get_correct_server_id():
    proxy = _mk_proxy()
    result = await build_overview(proxy)
    by_name = {t["name"]: t["server_id"] for t in result["tools"]}
    assert by_name["read_file"] == "cp::filesystem"
    # Runner tools with the "<mcp>__" prefix now route to the right bucket.
    assert by_name["slack__post_message"] == "runner:runner-a::slack"
    assert by_name["now"].startswith("native::")


@pytest.mark.asyncio
async def test_build_overview_cp_server_exposes_config():
    proxy = _mk_proxy()
    result = await build_overview(proxy)
    cp_server = next(s for s in result["servers"] if s["location"] == "control_plane")
    assert cp_server["config"]["transport"] == "stdio"
    assert cp_server["config"]["command"] == "/bin/fs"


@pytest.mark.asyncio
async def test_build_overview_accepts_runner_mcps_dict_shape():
    """Production CP returns runner 'mcps' as a dict keyed by name.

    Regression: earlier iteration treated this as a list and dropped
    command/args/env.
    """
    proxy = _mk_proxy()
    proxy.get_runner.return_value = {
        "mcps": {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                "transport": "stdio",
                "env": {"FOO": "bar"},
            }
        }
    }
    result = await build_overview(proxy)
    runner_srv = next(s for s in result["servers"] if s["location"].startswith("runner:"))
    assert runner_srv["name"] == "filesystem"
    assert runner_srv["command"] == "npx"
    assert runner_srv["config"]["args"] == [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/tmp",
    ]
    assert runner_srv["config"]["env"] == {"FOO": "bar"}


@pytest.mark.asyncio
async def test_runner_tools_route_to_mcp_by_double_underscore_prefix():
    """Real CP flattens runner tools as ``<mcp>__<tool>`` with
    source="runner" and server=<runner-name>. The inspector must peel the
    "<mcp>__" prefix and route the tool under that MCP server entry.
    """
    proxy = _mk_proxy()
    proxy.get_runner.return_value = {
        "mcps": {
            "github": {"command": "docker", "transport": "stdio"},
            "filesystem": {"command": "npx", "transport": "stdio"},
        }
    }
    proxy.list_tools.return_value = [
        {"name": "github__actions_get", "source": "runner", "server": "runner-a"},
        {"name": "github__pulls_list", "source": "runner", "server": "runner-a"},
        {"name": "filesystem__read_file", "source": "runner", "server": "runner-a"},
    ]
    result = await build_overview(proxy)
    by_name = {t["name"]: t["server_id"] for t in result["tools"]}
    assert by_name["github__actions_get"] == "runner:runner-a::github"
    assert by_name["github__pulls_list"] == "runner:runner-a::github"
    assert by_name["filesystem__read_file"] == "runner:runner-a::filesystem"

    github_srv = next(s for s in result["servers"] if s["id"] == "runner:runner-a::github")
    assert github_srv["tool_count"] == 2
    fs_srv = next(s for s in result["servers"] if s["id"] == "runner:runner-a::filesystem")
    assert fs_srv["tool_count"] == 1


@pytest.mark.asyncio
async def test_runner_tools_without_prefix_land_in_inline_bucket():
    """If a runner exposes tools that don't match any declared MCP prefix,
    we synthesize an ``<runner>-inline`` catch-all entry so they still
    show up in the tree rather than disappearing.
    """
    proxy = _mk_proxy()
    proxy.get_runner.return_value = {
        "mcps": {"github": {"command": "docker", "transport": "stdio"}}
    }
    proxy.list_tools.return_value = [
        {"name": "github__actions_get", "source": "runner", "server": "runner-a"},
        {"name": "misc_thing", "source": "runner", "server": "runner-a"},
    ]
    result = await build_overview(proxy)
    by_name = {t["name"]: t["server_id"] for t in result["tools"]}
    assert by_name["github__actions_get"] == "runner:runner-a::github"
    assert by_name["misc_thing"] == "runner:runner-a::runner-a-inline"

    inline = next(s for s in result["servers"] if s["id"].endswith("-inline"))
    assert inline["tool_count"] == 1
    assert inline["location"] == "runner:runner-a"


@pytest.mark.asyncio
async def test_system_tools_route_to_cp_system_server():
    """CP-builtin tools (source="system") must surface under a synthesized
    ``cp::system`` server so users can find them.
    """
    proxy = _mk_proxy()
    proxy.list_tools.return_value = [
        {"name": "python_exec", "source": "system", "server": "system"},
    ]
    result = await build_overview(proxy)
    system_srv = next(s for s in result["servers"] if s["name"] == "system")
    assert system_srv["id"] == "cp::system"
    assert system_srv["tool_count"] == 1
    tool_row = next(t for t in result["tools"] if t["name"] == "python_exec")
    assert tool_row["server_id"] == "cp::system"


@pytest.mark.asyncio
async def test_build_overview_tolerates_errors():
    proxy = AsyncMock()
    proxy.url = "http://cp:8022"
    proxy.get_capabilities.side_effect = models.InspectorProxyError("boom")
    proxy.health.side_effect = models.InspectorProxyError("boom")
    proxy.get_config.side_effect = models.InspectorProxyError("boom")
    proxy.list_runners.side_effect = models.InspectorProxyError("boom")
    proxy.list_tools.side_effect = models.InspectorProxyError("boom")

    result = await build_overview(proxy)
    assert result["servers"] == []
    assert result["tools"] == []
    assert result["cp"]["connected"] is False
