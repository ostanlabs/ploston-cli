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
    # Default: no virtual-server tools — tests that care opt in explicitly.
    proxy.mcp_tools_list.return_value = []
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
    proxy.mcp_tools_list.side_effect = models.InspectorProxyError("boom")

    result = await build_overview(proxy)
    assert result["servers"] == []
    assert result["tools"] == []
    assert result["cp"]["connected"] is False


# ── Prefix stripping + virtual servers ───────────────────────────


def test_bare_tool_name_strips_double_underscore():
    assert models._bare_tool_name("github__actions_get", "github") == "actions_get"


def test_bare_tool_name_strips_single_underscore_fallback():
    # The double-underscore form is canonical but older servers used
    # ``<mcp>_<tool>``; both should be peeled.
    assert models._bare_tool_name("fs_read", "fs") == "read"


def test_bare_tool_name_unchanged_when_no_prefix():
    assert models._bare_tool_name("standalone", "github") == "standalone"


def test_bare_tool_name_empty_inputs():
    # Defensive: missing mcp or tool name must be a no-op, not crash.
    assert models._bare_tool_name("", "github") == ""
    assert models._bare_tool_name("actions_get", "") == "actions_get"


@pytest.mark.asyncio
async def test_cp_server_tool_display_name_is_stripped():
    """CP-hosted MCP tools must display without the ``<mcp>__`` prefix."""
    proxy = _mk_proxy()
    # Replace the default read_file entry with a prefixed one so we can
    # assert the strip.
    proxy.list_tools.return_value = [
        {
            "name": "filesystem__read_file",
            "source": "mcp",
            "server": "filesystem",
            "description": "Reads files",
        },
    ]
    result = await build_overview(proxy)
    row = next(t for t in result["tools"] if t["name"] == "filesystem__read_file")
    assert row["display_name"] == "read_file"
    assert row["server_id"] == "cp::filesystem"


@pytest.mark.asyncio
async def test_runner_tool_display_name_is_stripped():
    proxy = _mk_proxy()
    proxy.get_runner.return_value = {
        "mcps": {"github": {"command": "docker", "transport": "stdio"}}
    }
    proxy.list_tools.return_value = [
        {"name": "github__actions_get", "source": "runner", "server": "runner-a"},
    ]
    result = await build_overview(proxy)
    row = next(t for t in result["tools"] if t["name"] == "github__actions_get")
    assert row["display_name"] == "actions_get"
    assert row["server_id"] == "runner:runner-a::github"
    # /mcp tools/call expects the full runner-prefixed name.
    assert row["mcp_call_name"] == "runner-a__github__actions_get"


@pytest.mark.asyncio
async def test_cp_tool_mcp_call_name_is_canonical():
    """CP-hosted system/mcp tools are exposed on /mcp by bare canonical
    name — no runner prefix to prepend.
    """
    proxy = _mk_proxy()
    proxy.list_tools.return_value = [
        {"name": "python_exec", "source": "system", "server": "system"},
        {
            "name": "filesystem__read_file",
            "source": "mcp",
            "server": "filesystem",
        },
    ]
    result = await build_overview(proxy)
    sys_row = next(t for t in result["tools"] if t["name"] == "python_exec")
    assert sys_row["mcp_call_name"] == "python_exec"
    fs_row = next(t for t in result["tools"] if t["name"] == "filesystem__read_file")
    assert fs_row["mcp_call_name"] == "filesystem__read_file"


@pytest.mark.asyncio
async def test_virtual_ploston_authoring_server_exposes_workflow_mgmt_tools():
    """The inspector must surface the same workflow_* authoring tools an
    agent would see via ``ploston bridge --expose ploston-authoring``.
    """
    proxy = _mk_proxy()

    async def _mcp_tools_list(tags=None):
        if tags == ["kind:workflow_mgmt"]:
            return [
                {
                    "name": "workflow_create",
                    "description": "Publish a workflow as an MCP tool.",
                    "inputSchema": {"type": "object", "required": ["yaml"]},
                },
                {
                    "name": "workflow_list",
                    "description": "List workflows.",
                    "inputSchema": {"type": "object"},
                },
            ]
        return []

    proxy.mcp_tools_list.side_effect = _mcp_tools_list
    result = await build_overview(proxy)

    auth = next(s for s in result["servers"] if s["name"] == "ploston-authoring")
    assert auth["virtual"] is True
    assert auth["location"] == "control_plane"
    assert auth["tool_count"] == 2
    # Synthetic bridge config so users know how to wire it up.
    assert auth["config"] == {
        "transport": "stdio",
        "command": "ploston",
        "args": ["bridge", "--expose", "ploston-authoring"],
    }

    create = next(t for t in result["tools"] if t["name"] == "workflow_create")
    assert create["server_id"] == "cp::ploston-authoring"
    # Exact MCP schema passes through (input_schema carries the bridge shape).
    assert create["input_schema"] == {"type": "object", "required": ["yaml"]}
    # Virtual tools are already bare-named, so display == canonical.
    assert create["display_name"] == "workflow_create"
    # /mcp accepts workflow mgmt tools by bare name.
    assert create["mcp_call_name"] == "workflow_create"


@pytest.mark.asyncio
async def test_virtual_ploston_server_exposes_workflow_tools():
    proxy = _mk_proxy()

    async def _mcp_tools_list(tags=None):
        if tags == ["kind:workflow"]:
            return [
                {
                    "name": "hello_world",
                    "description": "Hello world workflow.",
                    "inputSchema": {"type": "object", "properties": {"name": {}}},
                }
            ]
        return []

    proxy.mcp_tools_list.side_effect = _mcp_tools_list
    result = await build_overview(proxy)

    ploston = next(s for s in result["servers"] if s["name"] == "ploston")
    assert ploston["virtual"] is True
    assert ploston["tool_count"] == 1
    assert ploston["config"]["args"] == ["bridge", "--expose", "ploston"]

    hw = next(t for t in result["tools"] if t["name"] == "hello_world")
    assert hw["server_id"] == "cp::ploston"
    assert hw["input_schema"] == {"type": "object", "properties": {"name": {}}}


@pytest.mark.asyncio
async def test_virtual_servers_absent_when_no_tools_reported():
    """If the CP reports no workflow/authoring tools, the virtual buckets
    must not appear (e.g. workflows disabled, stripped-down deployments).
    """
    proxy = _mk_proxy()
    proxy.mcp_tools_list.return_value = []
    result = await build_overview(proxy)
    names = {s["name"] for s in result["servers"]}
    assert "ploston" not in names
    assert "ploston-authoring" not in names
