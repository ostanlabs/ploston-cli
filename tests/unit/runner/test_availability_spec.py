"""Specification tests for ploston_cli.runner.availability.AvailabilityReporter.

Asserts the intended contract:
- tool name prefixing (mcp__tool) in the read-only properties
- correct CP report payload shape (available tools w/ schema; unavailable MCPs
  w/ error + log_path + crash_snapshot)
- the report is skipped when the connection is down
- _perform_health_checks only re-reports on a status *transition*
- config -> MCPServerDefinition conversion (stdio vs http)
- not reporting when MCPManager absent / connection methods are no-ops

External boundaries faked: the RunnerConnection (send_notification / is_connected)
and the ploston-core MCPClientManager. The unit under test (AvailabilityReporter)
runs for real. ``ServerStatus`` / ``ConnectionStatus`` are the real core types.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from ploston_core.types import ConnectionStatus, MCPTransport

from ploston_cli.runner.availability import AvailabilityReporter
from ploston_cli.runner.types import (
    MCPAvailability,
    MCPConfig,
    MCPStatus,
    ToolInfo,
)


def _tool_schema(name: str, desc: str = "d", schema: dict | None = None):
    """A stand-in for ploston_core ToolSchema (attr access only)."""
    return SimpleNamespace(name=name, description=desc, input_schema=schema or {"type": "object"})


def _server_status(name, connected, error=None):
    return SimpleNamespace(
        name=name,
        status=ConnectionStatus.CONNECTED if connected else ConnectionStatus.ERROR,
        error=error,
    )


def _make_reporter(is_connected=True):
    conn = MagicMock()
    conn.is_connected = is_connected
    conn.send_notification = AsyncMock()
    return AvailabilityReporter(connection=conn), conn


# ---------------------------------------------------------------------------
# Read-only properties (tool prefixing)
# ---------------------------------------------------------------------------


def test_available_tools_are_prefixed_with_mcp_name():
    reporter, _ = _make_reporter()
    reporter._availability = {
        "github": MCPAvailability(
            name="github",
            status=MCPStatus.AVAILABLE,
            tools=[ToolInfo(name="search"), ToolInfo(name="create_issue")],
        ),
        "down": MCPAvailability(name="down", status=MCPStatus.UNAVAILABLE),
    }
    assert reporter.available_tools == ["github__search", "github__create_issue"]


def test_available_tools_with_schema_carries_description_and_schema():
    reporter, _ = _make_reporter()
    reporter._availability = {
        "fs": MCPAvailability(
            name="fs",
            status=MCPStatus.AVAILABLE,
            tools=[ToolInfo(name="read", description="reads", input_schema={"a": 1})],
        )
    }
    infos = reporter.available_tools_with_schema
    assert len(infos) == 1
    assert infos[0].name == "fs__read"
    assert infos[0].description == "reads"
    assert infos[0].input_schema == {"a": 1}


def test_unavailable_mcps_lists_only_unavailable():
    reporter, _ = _make_reporter()
    reporter._availability = {
        "ok": MCPAvailability(name="ok", status=MCPStatus.AVAILABLE),
        "bad": MCPAvailability(name="bad", status=MCPStatus.UNAVAILABLE),
        "unknown": MCPAvailability(name="unknown", status=MCPStatus.UNKNOWN),
    }
    assert reporter.unavailable_mcps == ["bad"]


def test_is_tool_available_uses_prefixed_names():
    reporter, _ = _make_reporter()
    reporter._availability = {
        "github": MCPAvailability(
            name="github", status=MCPStatus.AVAILABLE, tools=[ToolInfo(name="search")]
        )
    }
    assert reporter.is_tool_available("github__search") is True
    assert reporter.is_tool_available("search") is False
    assert reporter.is_tool_available("github__missing") is False


# ---------------------------------------------------------------------------
# MCPConfig -> MCPServerDefinition conversion
# ---------------------------------------------------------------------------


def test_config_to_server_def_http_when_url_present():
    reporter, _ = _make_reporter()
    cfg = MCPConfig(name="remote", url="https://x/sse")
    sd = reporter._mcp_config_to_server_def(cfg)
    assert sd.transport == MCPTransport.HTTP
    assert sd.url == "https://x/sse"


def test_config_to_server_def_stdio_joins_command_and_args():
    reporter, _ = _make_reporter()
    cfg = MCPConfig(name="gh", command="npx", args=["-y", "server"], env={"K": "v"})
    sd = reporter._mcp_config_to_server_def(cfg)
    assert sd.transport == MCPTransport.STDIO
    assert sd.command == "npx -y server"
    assert sd.env == {"K": "v"}


def test_config_to_server_def_stdio_without_args():
    reporter, _ = _make_reporter()
    cfg = MCPConfig(name="x", command="run-me")
    sd = reporter._mcp_config_to_server_def(cfg)
    assert sd.command == "run-me"


# ---------------------------------------------------------------------------
# _report_availability — payload shape & skip-when-disconnected
# ---------------------------------------------------------------------------


async def test_report_availability_skipped_when_not_connected():
    reporter, conn = _make_reporter(is_connected=False)
    reporter._availability = {
        "gh": MCPAvailability(name="gh", status=MCPStatus.AVAILABLE, tools=[ToolInfo(name="t")])
    }
    await reporter._report_availability()
    conn.send_notification.assert_not_called()


async def test_report_availability_sends_prefixed_tool_schemas():
    reporter, conn = _make_reporter(is_connected=True)
    reporter._availability = {
        "gh": MCPAvailability(
            name="gh",
            status=MCPStatus.AVAILABLE,
            tools=[ToolInfo(name="search", description="finds", input_schema={"q": 1})],
        )
    }
    await reporter._report_availability()

    conn.send_notification.assert_awaited_once()
    method, payload = conn.send_notification.await_args.args
    assert method == "runner/availability"
    assert payload["available"] == [
        {"name": "gh__search", "description": "finds", "inputSchema": {"q": 1}}
    ]
    assert payload["unavailable"] == []


async def test_report_availability_includes_error_and_log_path_for_unavailable(
    monkeypatch, tmp_path
):
    reporter, conn = _make_reporter(is_connected=True)

    log_file = tmp_path / "broken.log"
    log_file.write_text("line1\nline2\ncrash trace\n")
    monkeypatch.setattr("ploston_cli.runner.availability.mcp_log_path", lambda name: log_file)

    reporter._availability = {
        "broken": MCPAvailability(name="broken", status=MCPStatus.UNAVAILABLE, error="boom")
    }
    await reporter._report_availability()

    _, payload = conn.send_notification.await_args.args
    assert payload["available"] == []
    assert len(payload["unavailable"]) == 1
    entry = payload["unavailable"][0]
    assert entry["name"] == "broken"
    assert entry["error"] == "boom"
    assert entry["log_path"] == str(log_file)
    assert "crash trace" in entry["crash_snapshot"]


async def test_report_availability_default_error_when_none(monkeypatch, tmp_path):
    reporter, conn = _make_reporter(is_connected=True)
    missing_log = tmp_path / "nope.log"
    monkeypatch.setattr("ploston_cli.runner.availability.mcp_log_path", lambda name: missing_log)
    reporter._availability = {
        "x": MCPAvailability(name="x", status=MCPStatus.UNAVAILABLE, error=None)
    }
    await reporter._report_availability()
    _, payload = conn.send_notification.await_args.args
    entry = payload["unavailable"][0]
    assert entry["error"] == "unavailable"
    assert entry["crash_snapshot"] == ""  # log file absent


# ---------------------------------------------------------------------------
# _test_all_mcps — translates manager statuses into availability
# ---------------------------------------------------------------------------


async def test_test_all_mcps_records_available_with_tools_and_unavailable_with_error():
    reporter, _ = _make_reporter()

    manager = MagicMock()
    manager.connect_all = AsyncMock(
        return_value={
            "gh": _server_status("gh", connected=True),
            "bad": _server_status("bad", connected=False, error="spawn failed"),
        }
    )
    conn = MagicMock()
    conn.list_tools = MagicMock(return_value=[_tool_schema("search")])
    manager.get_connection = MagicMock(return_value=conn)
    reporter._mcp_manager = manager

    await reporter._test_all_mcps()

    gh = reporter._availability["gh"]
    assert gh.status == MCPStatus.AVAILABLE
    assert [t.name for t in gh.tools] == ["search"]

    bad = reporter._availability["bad"]
    assert bad.status == MCPStatus.UNAVAILABLE
    assert bad.error == "spawn failed"


async def test_test_all_mcps_noop_without_manager():
    reporter, _ = _make_reporter()
    reporter._mcp_manager = None
    await reporter._test_all_mcps()  # must not raise
    assert reporter._availability == {}


# ---------------------------------------------------------------------------
# _perform_health_checks — only re-report on transitions
# ---------------------------------------------------------------------------


async def test_health_check_reports_on_status_transition(monkeypatch):
    reporter, conn = _make_reporter(is_connected=True)
    monkeypatch.setattr(
        "ploston_cli.runner.availability.mcp_log_path",
        lambda name: __import__("pathlib").Path("/nonexistent/x.log"),
    )

    # Was AVAILABLE, now manager says ERROR -> transition -> must re-report.
    reporter._availability = {
        "gh": MCPAvailability(name="gh", status=MCPStatus.AVAILABLE, tools=[ToolInfo("t")])
    }
    manager = MagicMock()
    manager.get_status = MagicMock(
        return_value={"gh": _server_status("gh", connected=False, error="died")}
    )
    manager.get_connection = MagicMock(return_value=None)
    reporter._mcp_manager = manager

    await reporter._perform_health_checks()

    assert reporter._availability["gh"].status == MCPStatus.UNAVAILABLE
    conn.send_notification.assert_awaited_once()


async def test_health_check_does_not_report_when_status_unchanged():
    reporter, conn = _make_reporter(is_connected=True)

    reporter._availability = {
        "gh": MCPAvailability(name="gh", status=MCPStatus.AVAILABLE, tools=[ToolInfo("t")])
    }
    tool_conn = MagicMock()
    tool_conn.list_tools = MagicMock(return_value=[_tool_schema("t")])
    manager = MagicMock()
    manager.get_status = MagicMock(return_value={"gh": _server_status("gh", connected=True)})
    manager.get_connection = MagicMock(return_value=tool_conn)
    reporter._mcp_manager = manager

    await reporter._perform_health_checks()

    # Still AVAILABLE; no transition -> no report.
    assert reporter._availability["gh"].status == MCPStatus.AVAILABLE
    conn.send_notification.assert_not_called()


async def test_health_check_noop_without_manager():
    reporter, conn = _make_reporter()
    reporter._mcp_manager = None
    await reporter._perform_health_checks()
    conn.send_notification.assert_not_called()


# ---------------------------------------------------------------------------
# stop() lifecycle
# ---------------------------------------------------------------------------


async def test_stop_disconnects_manager_and_clears_state():
    reporter, _ = _make_reporter()
    manager = MagicMock()
    manager.disconnect_all = AsyncMock()
    reporter._mcp_manager = manager
    reporter._should_run = True

    await reporter.stop()

    manager.disconnect_all.assert_awaited_once()
    assert reporter._mcp_manager is None
    assert reporter._should_run is False


def test_get_mcp_manager_returns_current_manager():
    reporter, _ = _make_reporter()
    assert reporter.get_mcp_manager() is None
    sentinel = MagicMock()
    reporter._mcp_manager = sentinel
    assert reporter.get_mcp_manager() is sentinel


# ---------------------------------------------------------------------------
# _rotate_mcp_log — filesystem boundary
# ---------------------------------------------------------------------------


def test_rotate_mcp_log_renames_current_to_dot1(monkeypatch, tmp_path):
    log = tmp_path / "gh.log"
    log.write_text("current contents")
    monkeypatch.setattr("ploston_cli.runner.availability.mcp_log_path", lambda name: log)

    AvailabilityReporter._rotate_mcp_log("gh")

    assert not log.exists()
    rotated = tmp_path / "gh.log.1"
    assert rotated.exists()
    assert rotated.read_text() == "current contents"


def test_rotate_mcp_log_replaces_existing_dot1(monkeypatch, tmp_path):
    """At most 2 files kept: an existing .log.1 is removed before rotation."""
    log = tmp_path / "gh.log"
    log.write_text("new")
    old = tmp_path / "gh.log.1"
    old.write_text("stale previous")
    monkeypatch.setattr("ploston_cli.runner.availability.mcp_log_path", lambda name: log)

    AvailabilityReporter._rotate_mcp_log("gh")

    rotated = tmp_path / "gh.log.1"
    assert rotated.read_text() == "new"
    assert not log.exists()


def test_rotate_mcp_log_noop_when_no_log(monkeypatch, tmp_path):
    log = tmp_path / "absent.log"
    monkeypatch.setattr("ploston_cli.runner.availability.mcp_log_path", lambda name: log)
    AvailabilityReporter._rotate_mcp_log("absent")  # must not raise
    assert not log.exists()


# ---------------------------------------------------------------------------
# _health_check_loop — periodic invocation & clean cancellation
# ---------------------------------------------------------------------------


async def test_health_check_loop_invokes_checks_then_exits_on_cancel():
    import asyncio

    reporter, _ = _make_reporter()
    reporter._health_check_interval = 0  # don't actually wait
    reporter._should_run = True

    calls = {"n": 0}

    async def fake_checks():
        calls["n"] += 1
        if calls["n"] >= 2:
            reporter._should_run = False  # let the loop terminate naturally

    reporter._perform_health_checks = fake_checks  # type: ignore[assignment]

    await asyncio.wait_for(reporter._health_check_loop(), timeout=2.0)
    assert calls["n"] >= 2


async def test_health_check_loop_survives_transient_check_error():
    """A health-check exception must be logged and the loop must continue."""
    import asyncio

    reporter, _ = _make_reporter()
    reporter._health_check_interval = 0
    reporter._should_run = True

    calls = {"n": 0}

    async def flaky_checks():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        reporter._should_run = False

    reporter._perform_health_checks = flaky_checks  # type: ignore[assignment]

    await asyncio.wait_for(reporter._health_check_loop(), timeout=2.0)
    assert calls["n"] >= 2  # continued past the error
