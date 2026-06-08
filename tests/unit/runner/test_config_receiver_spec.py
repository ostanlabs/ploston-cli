"""Specification tests for ploston_cli.runner.config_receiver.ConfigReceiver.

Asserts the intended contract: config/push parsing into MCPConfig objects,
${VAR} environment-variable resolution (resolved when set, left intact and
warned when unset), per-MCP parse-failure isolation, async callback invocation,
and the lookup helpers.

The only external boundary is os.environ, exercised via monkeypatch.
"""

from __future__ import annotations

from ploston_cli.runner.config_receiver import ConfigReceiver
from ploston_cli.runner.types import MCPConfig, RunnerMCPConfig

# ---------------------------------------------------------------------------
# Environment variable resolution
# ---------------------------------------------------------------------------


def test_env_var_resolved_when_set(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "secret123")
    receiver = ConfigReceiver()
    assert receiver._resolve_env_vars("Bearer ${MY_TOKEN}") == "Bearer secret123"


def test_env_var_left_intact_when_unset(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    receiver = ConfigReceiver()
    # Contract: unresolved references are left as-is for debugging.
    assert receiver._resolve_env_vars("x=${MISSING_VAR}") == "x=${MISSING_VAR}"


def test_env_var_multiple_references_in_one_string(monkeypatch):
    monkeypatch.setenv("A", "1")
    monkeypatch.setenv("B", "2")
    receiver = ConfigReceiver()
    assert receiver._resolve_env_vars("${A}-${B}") == "1-2"


def test_env_var_string_without_references_unchanged():
    receiver = ConfigReceiver()
    assert receiver._resolve_env_vars("plain value") == "plain value"


def test_resolve_env_dict_resolves_each_value(monkeypatch):
    monkeypatch.setenv("KEY", "resolved")
    receiver = ConfigReceiver()
    result = receiver._resolve_env_dict({"TOKEN": "${KEY}", "STATIC": "x"})
    assert result == {"TOKEN": "resolved", "STATIC": "x"}


# ---------------------------------------------------------------------------
# Parsing single MCP config
# ---------------------------------------------------------------------------


def test_parse_mcp_config_stdio_with_env_resolution(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_abc")
    receiver = ConfigReceiver()
    cfg = receiver._parse_mcp_config(
        "github",
        {
            "command": "npx",
            "args": ["-y", "server"],
            "env": {"TOKEN": "${GH_TOKEN}"},
        },
    )
    assert isinstance(cfg, MCPConfig)
    assert cfg.name == "github"
    assert cfg.command == "npx"
    assert cfg.args == ["-y", "server"]
    assert cfg.env == {"TOKEN": "ghp_abc"}
    assert cfg.url is None


def test_parse_mcp_config_http_url():
    receiver = ConfigReceiver()
    cfg = receiver._parse_mcp_config("remote", {"url": "https://mcp.example/sse"})
    assert cfg.url == "https://mcp.example/sse"
    assert cfg.command == ""
    assert cfg.args == []


def test_parse_mcp_config_defaults_for_minimal_dict():
    receiver = ConfigReceiver()
    cfg = receiver._parse_mcp_config("minimal", {})
    assert cfg.command == ""
    assert cfg.args == []
    assert cfg.env == {}
    assert cfg.url is None


# ---------------------------------------------------------------------------
# handle_config_push contract
# ---------------------------------------------------------------------------


async def test_handle_config_push_parses_all_and_returns_ok():
    receiver = ConfigReceiver()
    params = {
        "mcps": {
            "github": {"command": "npx", "args": ["server"]},
            "remote": {"url": "https://x/sse"},
        }
    }
    result = await receiver.handle_config_push(params)
    assert result == {"status": "ok", "mcps_received": 2}
    assert receiver.current_config is not None
    assert set(receiver.list_mcp_names()) == {"github", "remote"}


async def test_handle_config_push_empty_mcps_returns_zero():
    receiver = ConfigReceiver()
    result = await receiver.handle_config_push({"mcps": {}})
    assert result == {"status": "ok", "mcps_received": 0}
    assert receiver.list_mcp_names() == []


async def test_handle_config_push_missing_mcps_key_treated_as_empty():
    receiver = ConfigReceiver()
    result = await receiver.handle_config_push({})
    assert result["status"] == "ok"
    assert result["mcps_received"] == 0


async def test_handle_config_push_invokes_async_callback_with_config():
    received: list[RunnerMCPConfig] = []

    async def cb(config: RunnerMCPConfig) -> None:
        received.append(config)

    receiver = ConfigReceiver(on_config_received=cb)
    await receiver.handle_config_push({"mcps": {"a": {"command": "c"}}})
    assert len(received) == 1
    assert isinstance(received[0], RunnerMCPConfig)
    assert "a" in received[0].mcps


async def test_handle_config_push_skips_unparseable_entry_but_keeps_others():
    """A single malformed MCP entry must not abort the whole push.

    Per-entry parsing is wrapped in try/except; valid siblings are retained.
    """
    receiver = ConfigReceiver()
    params = {
        "mcps": {
            "good": {"command": "ok"},
            "bad": "not-a-dict",  # .get() on a str raises -> skipped
        }
    }
    result = await receiver.handle_config_push(params)
    assert result["status"] == "ok"
    assert result["mcps_received"] == 1
    assert receiver.list_mcp_names() == ["good"]


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def test_get_mcp_config_returns_none_before_any_push():
    receiver = ConfigReceiver()
    assert receiver.get_mcp_config("anything") is None
    assert receiver.list_mcp_names() == []


async def test_get_mcp_config_returns_config_after_push():
    receiver = ConfigReceiver()
    await receiver.handle_config_push({"mcps": {"a": {"command": "c"}}})
    cfg = receiver.get_mcp_config("a")
    assert cfg is not None and cfg.name == "a"
    assert receiver.get_mcp_config("missing") is None
