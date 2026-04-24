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
        {
            "name": "post_message",
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
    assert cp_servers[0]["tool_count"] == 3
    assert cp_servers[0]["status"] == "connected"


@pytest.mark.asyncio
async def test_build_overview_includes_runner_server():
    proxy = _mk_proxy()
    result = await build_overview(proxy)
    runner_servers = [s for s in result["servers"] if s["location"].startswith("runner:")]
    assert len(runner_servers) == 1
    assert runner_servers[0]["id"] == "runner:runner-a::slack"


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
    assert by_name["post_message"] == "runner:runner-a::runner-a"
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
