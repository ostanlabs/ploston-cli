"""Specification-driven tests for `ploston server` (commands/server.py).

These tests assert the INTENDED contract of the server command group
(list / add / remove): each subcommand must call the correct PlostClient
operation with the correct arguments, render the correct output, and handle
error conditions (not found, server unreachable, bad input) with the correct
exit codes / messages.

Boundary mocked: PlostClient (the Control-Plane HTTP client). Command logic
itself is exercised through Click's CliRunner.

Contract reference: DEC169-175_ROUTING_TAGS_CLI_SPEC.md §6 (T-768).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ploston_cli.client import PlostClientError
from ploston_cli.main import cli

SRV = "ploston_cli.commands.server.PlostClient"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _client(**methods) -> AsyncMock:
    """Build an AsyncMock PlostClient instance with async-context support."""
    inst = AsyncMock()
    inst.__aenter__ = AsyncMock(return_value=inst)
    inst.__aexit__ = AsyncMock(return_value=False)
    for name, value in methods.items():
        setattr(inst, name, value)
    return inst


# ---------------------------------------------------------------------------
# server list
# ---------------------------------------------------------------------------


class TestServerList:
    def _wire(self, mock_cls, runners, details):
        inst = _client(
            list_runners=AsyncMock(return_value=runners),
            get_runner=AsyncMock(side_effect=lambda name: details[name]),
        )
        mock_cls.return_value = inst
        return inst

    def test_lists_each_mcp_with_runner_and_transport(self, runner):
        """Every MCP across runners is listed with its runner + transport."""
        runners = [{"name": "mac", "status": "connected"}]
        details = {
            "mac": {
                "mcps": {
                    "filesystem": {"command": "node", "args": ["fs"]},
                    "remotegit": {"url": "https://example/sse"},
                },
                "available_tools": [
                    {"name": "filesystem__read_file"},
                    {"name": "filesystem__write_file"},
                    {"name": "remotegit__clone"},
                ],
            }
        }
        with patch(SRV) as mock_cls:
            inst = self._wire(mock_cls, runners, details)
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "list"])

        assert result.exit_code == 0, result.output
        inst.list_runners.assert_awaited_once()
        inst.get_runner.assert_awaited_once_with("mac")
        assert "filesystem" in result.output
        assert "remotegit" in result.output
        # stdio (command) vs sse (url) transports inferred correctly
        assert "transport=stdio" in result.output
        assert "transport=sse" in result.output
        # tool counts grouped by server prefix
        assert "tools=2" in result.output  # filesystem has 2
        assert "tools=1" in result.output  # remotegit has 1

    def test_json_output_emits_structured_list(self, runner):
        runners = [{"name": "mac", "status": "connected"}]
        details = {
            "mac": {
                "mcps": {"fs": {"command": "node"}},
                "available_tools": [{"name": "fs__t1"}, {"name": "fs__t2"}],
            }
        }
        with patch(SRV) as mock_cls:
            self._wire(mock_cls, runners, details)
            result = runner.invoke(cli, ["-s", "http://cp:8022", "--json", "server", "list"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        entry = data[0]
        assert entry["name"] == "fs"
        assert entry["runner"] == "mac"
        assert entry["transport"] == "stdio"
        assert entry["tool_count"] == 2
        assert sorted(entry["tools"]) == ["t1", "t2"]

    def test_empty_when_no_servers_configured(self, runner):
        """No runners / no MCPs → friendly 'none' message, success exit."""
        with patch(SRV) as mock_cls:
            self._wire(mock_cls, [], {})
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "list"])

        assert result.exit_code == 0, result.output
        assert "No MCP servers configured" in result.output

    def test_empty_json_is_empty_array(self, runner):
        with patch(SRV) as mock_cls:
            self._wire(mock_cls, [], {})
            result = runner.invoke(cli, ["-s", "http://cp:8022", "--json", "server", "list"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == []

    def test_unknown_transport_when_no_command_or_url(self, runner):
        """An MCP entry with neither command nor url → transport 'unknown'."""
        runners = [{"name": "mac", "status": "connected"}]
        details = {"mac": {"mcps": {"weird": {}}, "available_tools": []}}
        with patch(SRV) as mock_cls:
            self._wire(mock_cls, runners, details)
            result = runner.invoke(cli, ["-s", "http://cp:8022", "--json", "server", "list"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)[0]["transport"] == "unknown"

    def test_show_tools_flag_lists_individual_tool_names(self, runner):
        runners = [{"name": "mac", "status": "connected"}]
        details = {
            "mac": {
                "mcps": {"fs": {"command": "node"}},
                "available_tools": [{"name": "fs__write"}, {"name": "fs__read"}],
            }
        }
        with patch(SRV) as mock_cls:
            self._wire(mock_cls, runners, details)
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "list", "--tools"])

        assert result.exit_code == 0, result.output
        assert "- read" in result.output
        assert "- write" in result.output
        # tools should be displayed sorted
        assert result.output.index("- read") < result.output.index("- write")

    def test_server_unreachable_exits_1_with_error(self, runner):
        """Client connection error → stderr message + exit code 1."""
        inst = _client(list_runners=AsyncMock(side_effect=PlostClientError("connection refused")))
        with patch(SRV, return_value=inst):
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "list"])

        assert result.exit_code == 1
        assert "connection refused" in result.output
        assert "Error:" in result.output

    def test_status_icon_reflects_runner_status(self, runner):
        """Connected runner uses filled icon; disconnected uses hollow."""
        runners = [{"name": "r1", "status": "disconnected"}]
        details = {
            "r1": {"mcps": {"x": {"command": "c"}}, "available_tools": []},
        }
        with patch(SRV) as mock_cls:
            self._wire(mock_cls, runners, details)
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "list"])
        assert result.exit_code == 0, result.output
        assert "○" in result.output  # hollow = disconnected
        assert "●" not in result.output


# ---------------------------------------------------------------------------
# server add (manual mode)
# ---------------------------------------------------------------------------


class TestServerAddManual:
    def test_pushes_config_with_command_args_merge_true(self, runner):
        push = AsyncMock(return_value={})
        inst = _client(
            get_runner_token=AsyncMock(return_value="tok"),
            push_runner_config=push,
        )
        with patch(SRV, return_value=inst):
            result = runner.invoke(
                cli,
                [
                    "-s",
                    "http://cp:8022",
                    "server",
                    "add",
                    "fetch",
                    "--command",
                    "npx",
                    "--args",
                    '["@mcp/fetch"]',
                ],
            )
        assert result.exit_code == 0, result.output
        assert "fetch" in result.output
        kwargs = push.call_args.kwargs
        assert kwargs["merge"] is True
        assert kwargs["mcp_servers"]["fetch"]["command"] == "npx"
        assert kwargs["mcp_servers"]["fetch"]["args"] == ["@mcp/fetch"]

    def test_env_vars_parsed_into_config(self, runner):
        push = AsyncMock(return_value={})
        inst = _client(
            get_runner_token=AsyncMock(return_value="tok"),
            push_runner_config=push,
        )
        with patch(SRV, return_value=inst):
            result = runner.invoke(
                cli,
                [
                    "-s",
                    "http://cp:8022",
                    "server",
                    "add",
                    "gh",
                    "--command",
                    "npx",
                    "--env",
                    "TOKEN=abc",
                    "--env",
                    "REGION=us",
                ],
            )
        assert result.exit_code == 0, result.output
        env = push.call_args.kwargs["mcp_servers"]["gh"]["env"]
        assert env == {"TOKEN": "abc", "REGION": "us"}

    def test_missing_command_is_usage_error(self, runner):
        """`add <name>` without --command (and no --detect) → usage error."""
        with patch(SRV, return_value=_client()):
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "add", "fetch"])
        assert result.exit_code != 0
        assert "command" in result.output.lower()

    def test_no_name_no_detect_is_usage_error(self, runner):
        result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "add"])
        assert result.exit_code != 0

    def test_invalid_args_json_is_bad_parameter(self, runner):
        """--args with malformed JSON → BadParameter (exit 2), no push attempted."""
        push = AsyncMock(return_value={})
        inst = _client(get_runner_token=AsyncMock(return_value="t"), push_runner_config=push)
        with patch(SRV, return_value=inst):
            result = runner.invoke(
                cli,
                [
                    "-s",
                    "http://cp:8022",
                    "server",
                    "add",
                    "x",
                    "--command",
                    "npx",
                    "--args",
                    "not-json",
                ],
            )
        assert result.exit_code != 0
        assert "JSON" in result.output or "json" in result.output
        push.assert_not_called()

    def test_env_without_equals_is_bad_parameter(self, runner):
        push = AsyncMock(return_value={})
        inst = _client(get_runner_token=AsyncMock(return_value="t"), push_runner_config=push)
        with patch(SRV, return_value=inst):
            result = runner.invoke(
                cli,
                [
                    "-s",
                    "http://cp:8022",
                    "server",
                    "add",
                    "x",
                    "--command",
                    "npx",
                    "--env",
                    "NOEQUALS",
                ],
            )
        assert result.exit_code != 0
        assert "KEY=VAL" in result.output
        push.assert_not_called()

    def test_push_error_exits_1(self, runner):
        """Server rejects the config push → error message + exit 1."""
        inst = _client(
            get_runner_token=AsyncMock(return_value="tok"),
            push_runner_config=AsyncMock(side_effect=PlostClientError("conflict: already exists")),
        )
        with patch(SRV, return_value=inst):
            result = runner.invoke(
                cli,
                ["-s", "http://cp:8022", "server", "add", "fetch", "--command", "npx"],
            )
        assert result.exit_code == 1
        assert "conflict: already exists" in result.output

    def test_token_lookup_failure_falls_back_to_auto(self, runner):
        """If runner token can't be fetched, push proceeds with 'auto' token."""
        push = AsyncMock(return_value={})
        inst = _client(
            get_runner_token=AsyncMock(side_effect=PlostClientError("no runner")),
            push_runner_config=push,
        )
        with patch(SRV, return_value=inst):
            result = runner.invoke(
                cli,
                ["-s", "http://cp:8022", "server", "add", "fetch", "--command", "npx"],
            )
        assert result.exit_code == 0, result.output
        assert push.call_args.kwargs["token"] == "auto"


# ---------------------------------------------------------------------------
# server add --inject / --inject-target
# ---------------------------------------------------------------------------


class TestServerAddInject:
    def test_inject_flag_calls_inject_after_add(self, runner):
        """--inject triggers the post-add injection step with the CP url."""
        push = AsyncMock(return_value={})
        inst = _client(
            get_runner_token=AsyncMock(return_value="tok"),
            push_runner_config=push,
        )
        with (
            patch(SRV, return_value=inst),
            patch("ploston_cli.commands.server._run_inject_after_add") as mock_after,
        ):
            result = runner.invoke(
                cli,
                ["-s", "http://cp:8022", "server", "add", "fetch", "--command", "npx", "--inject"],
            )
        assert result.exit_code == 0, result.output
        mock_after.assert_called_once()
        assert mock_after.call_args.kwargs["server_url"] == "http://cp:8022"
        assert mock_after.call_args.kwargs["inject_targets"] is None

    def test_inject_target_implies_inject(self, runner):
        """Passing --inject-target turns on injection even without --inject."""
        push = AsyncMock(return_value={})
        inst = _client(
            get_runner_token=AsyncMock(return_value="tok"),
            push_runner_config=push,
        )
        with (
            patch(SRV, return_value=inst),
            patch("ploston_cli.commands.server._run_inject_after_add") as mock_after,
        ):
            result = runner.invoke(
                cli,
                [
                    "-s",
                    "http://cp:8022",
                    "server",
                    "add",
                    "fetch",
                    "--command",
                    "npx",
                    "--inject-target",
                    "cursor",
                ],
            )
        assert result.exit_code == 0, result.output
        mock_after.assert_called_once()
        assert mock_after.call_args.kwargs["inject_targets"] == ["cursor"]

    def test_invalid_inject_target_rejected(self, runner):
        result = runner.invoke(
            cli,
            [
                "-s",
                "http://cp:8022",
                "server",
                "add",
                "fetch",
                "--command",
                "npx",
                "--inject-target",
                "not-a-real-target",
            ],
        )
        assert result.exit_code != 0


class TestRunInjectAfterAdd:
    """Directly exercise the post-add injection helper."""

    def _detected(self, found=True):
        d = MagicMock()
        d.found = found
        d.path = "/tmp/claude.json"
        d.source = "claude_desktop"
        return d

    def test_no_configs_detected_skips_injection(self, capsys):
        from ploston_cli.commands import server as mod

        with patch("ploston_cli.init.ConfigDetector") as mock_det:
            mock_det.return_value.detect_all.return_value = [self._detected(found=False)]
            mod._run_inject_after_add(server_url="http://cp:8022")

        out = capsys.readouterr().out
        assert "No agent configs detected" in out

    def test_server_list_fetch_failure_aborts_with_warning(self, capsys):
        from ploston_cli.commands import server as mod

        client = _client(list_tools=AsyncMock(side_effect=PlostClientError("down")))
        with (
            patch("ploston_cli.init.ConfigDetector") as mock_det,
            patch("ploston_cli.commands.server.PlostClient", return_value=client),
            patch("ploston_cli.commands.server.run_injection") as mock_inject,
        ):
            mock_det.return_value.detect_all.return_value = [self._detected()]
            mod._run_inject_after_add(server_url="http://cp:8022")

        out = capsys.readouterr().out
        assert "Could not fetch server list" in out
        mock_inject.assert_not_called()

    def test_success_reports_each_target_result(self, capsys):
        """End-to-end happy path: fetch server list from CP (real coroutine),
        filter native/workflow sources, and report per-target injection result."""
        from ploston_cli.commands import server as mod

        # list_tools shape: include a native + workflow entry that must be filtered out,
        # and two real MCP servers (deduped + sorted).
        client = _client(
            list_tools=AsyncMock(
                return_value=[
                    {"name": "t1", "server": "fetch"},
                    {"name": "t2", "source": "github"},
                    {"name": "t3", "server": "native"},
                    {"name": "t4", "source": "workflow"},
                    {"name": "t5", "server": "fetch"},  # duplicate server
                ]
            )
        )
        with (
            patch("ploston_cli.init.ConfigDetector") as mock_det,
            patch("ploston_cli.commands.server.PlostClient", return_value=client),
            patch("ploston_cli.commands.server.run_injection") as mock_inject,
        ):
            mock_det.return_value.detect_all.return_value = [self._detected()]
            mock_inject.return_value = [
                ("claude_desktop", "/tmp/claude.json", None),
                ("cursor", None, "permission denied"),
            ]
            mod._run_inject_after_add(server_url="http://cp:8022")

        out = capsys.readouterr().out
        assert "/tmp/claude.json" in out  # success line
        assert "permission denied" in out  # error line
        # native/workflow filtered; duplicates collapsed; result sorted
        assert mock_inject.call_args.kwargs["imported_servers"] == ["fetch", "github"]


# ---------------------------------------------------------------------------
# server add --detect
# ---------------------------------------------------------------------------


class TestServerAddDetect:
    def _patch_detect(self, servers, already=None, selected=None):
        """Return a context manager set patching detect-mode collaborators."""
        from contextlib import ExitStack

        stack = ExitStack()
        mock_det = stack.enter_context(patch("ploston_cli.init.ConfigDetector"))
        mock_sel = stack.enter_context(patch("ploston_cli.init.ServerSelector"))
        mock_merge = stack.enter_context(patch("ploston_cli.init.merge_configs"))
        mock_merge.return_value = servers
        mock_det.return_value.detect_all.return_value = []
        sel_inst = mock_sel.return_value
        sel_inst.prompt_selection = AsyncMock(
            return_value=selected if selected is not None else list(servers)
        )
        return stack, mock_merge, sel_inst

    def test_detect_no_servers_found(self, runner):
        stack, _, _ = self._patch_detect({})
        with stack, patch(SRV, return_value=_client()):
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "add", "--detect"])
        assert result.exit_code == 0, result.output
        assert "No MCP servers detected" in result.output

    def test_detect_pushes_selected_servers(self, runner):
        from ploston_cli.init.detector import ServerInfo

        servers = {
            "fs": ServerInfo(
                name="fs",
                source="claude_desktop",
                command="node",
                args=["s"],
                env={"K": "V"},
            ),
        }
        push = AsyncMock(return_value=None)
        inst = _client(
            get_runner_token=AsyncMock(return_value="tok"),
            push_runner_config=push,
            _request=AsyncMock(return_value={"mcp_servers": {}}),
        )
        stack, _, _ = self._patch_detect(servers, selected=["fs"])
        with stack, patch(SRV, return_value=inst):
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "add", "--detect"])
        assert result.exit_code == 0, result.output
        assert "fs" in result.output
        entry = push.call_args.kwargs["mcp_servers"]["fs"]
        assert entry["command"] == "node"
        assert entry["args"] == ["s"]
        assert entry["env"] == {"K": "V"}

    def test_detect_skips_already_registered_but_adds_new(self, runner):
        """When some detected servers already exist, they're skipped and the
        rest are still offered/added; a 'Skipping already registered' note shows."""
        from ploston_cli.init.detector import ServerInfo

        servers = {
            "fs": ServerInfo(name="fs", source="claude_desktop", command="node"),
            "gh": ServerInfo(name="gh", source="claude_desktop", command="npx"),
        }
        push = AsyncMock(return_value=None)
        inst = _client(
            get_runner_token=AsyncMock(return_value="tok"),
            push_runner_config=push,
            _request=AsyncMock(return_value={"mcp_servers": {"fs": {}}}),
        )
        stack, _, _ = self._patch_detect(servers, selected=["gh"])
        with stack, patch(SRV, return_value=inst):
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "add", "--detect"])
        assert result.exit_code == 0, result.output
        assert "Skipping already registered" in result.output
        assert "fs" in result.output  # the skipped one is named
        assert "gh" in push.call_args.kwargs["mcp_servers"]
        assert "fs" not in push.call_args.kwargs["mcp_servers"]

    def test_detect_token_fallback_to_auto(self, runner):
        """If runner token can't be fetched in detect mode, push uses 'auto'."""
        from ploston_cli.init.detector import ServerInfo

        servers = {"fs": ServerInfo(name="fs", source="claude_desktop", command="node")}
        push = AsyncMock(return_value=None)
        inst = _client(
            get_runner_token=AsyncMock(side_effect=PlostClientError("no token")),
            push_runner_config=push,
            _request=AsyncMock(return_value={"mcp_servers": {}}),
        )
        stack, _, _ = self._patch_detect(servers, selected=["fs"])
        with stack, patch(SRV, return_value=inst):
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "add", "--detect"])
        assert result.exit_code == 0, result.output
        assert push.call_args.kwargs["token"] == "auto"

    def test_detect_get_existing_error_treated_as_empty(self, runner):
        """If reading existing runner config fails, treat as no servers
        registered (everything detected is addable)."""
        from ploston_cli.init.detector import ServerInfo

        servers = {"fs": ServerInfo(name="fs", source="claude_desktop", command="node")}
        push = AsyncMock(return_value=None)
        inst = _client(
            get_runner_token=AsyncMock(return_value="tok"),
            push_runner_config=push,
            _request=AsyncMock(side_effect=PlostClientError("config read failed")),
        )
        stack, _, _ = self._patch_detect(servers, selected=["fs"])
        with stack, patch(SRV, return_value=inst):
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "add", "--detect"])
        assert result.exit_code == 0, result.output
        assert "fs" in push.call_args.kwargs["mcp_servers"]

    def test_detect_with_inject_runs_injection(self, runner):
        from ploston_cli.init.detector import ServerInfo

        servers = {"fs": ServerInfo(name="fs", source="claude_desktop", command="node")}
        inst = _client(
            get_runner_token=AsyncMock(return_value="tok"),
            push_runner_config=AsyncMock(return_value=None),
            _request=AsyncMock(return_value={"mcp_servers": {}}),
        )
        stack, _, _ = self._patch_detect(servers, selected=["fs"])
        with (
            stack,
            patch(SRV, return_value=inst),
            patch("ploston_cli.commands.server._run_inject_after_add") as mock_after,
        ):
            result = runner.invoke(
                cli, ["-s", "http://cp:8022", "server", "add", "--detect", "--inject"]
            )
        assert result.exit_code == 0, result.output
        mock_after.assert_called_once()

    def test_detect_push_error_exits_1(self, runner):
        from ploston_cli.init.detector import ServerInfo

        servers = {"fs": ServerInfo(name="fs", source="claude_desktop", command="node")}
        inst = _client(
            get_runner_token=AsyncMock(return_value="tok"),
            push_runner_config=AsyncMock(side_effect=PlostClientError("server down")),
            _request=AsyncMock(return_value={"mcp_servers": {}}),
        )
        stack, _, _ = self._patch_detect(servers, selected=["fs"])
        with stack, patch(SRV, return_value=inst):
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "add", "--detect"])
        assert result.exit_code == 1
        assert "server down" in result.output

    def test_detect_nothing_selected(self, runner):
        from ploston_cli.init.detector import ServerInfo

        servers = {"fs": ServerInfo(name="fs", source="claude_desktop", command="node")}
        inst = _client(_request=AsyncMock(return_value={"mcp_servers": {}}))
        stack, _, _ = self._patch_detect(servers, selected=[])
        with stack, patch(SRV, return_value=inst):
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "add", "--detect"])
        assert result.exit_code == 0, result.output
        assert "No servers selected" in result.output

    def test_detect_all_already_registered(self, runner):
        from ploston_cli.init.detector import ServerInfo

        servers = {"fs": ServerInfo(name="fs", source="claude_desktop", command="node")}
        inst = _client(_request=AsyncMock(return_value={"mcp_servers": {"fs": {}}}))
        stack, _, _ = self._patch_detect(servers)
        with stack, patch(SRV, return_value=inst):
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "add", "--detect"])
        assert result.exit_code == 0, result.output
        assert "already registered" in result.output.lower()


# ---------------------------------------------------------------------------
# server remove
# ---------------------------------------------------------------------------


class TestServerRemove:
    def test_remove_existing_pushes_without_that_server(self, runner):
        existing = {
            "mcp_servers": {"github": {"command": "npx"}, "fs": {"command": "node"}},
            "token": "tok",
        }
        push = AsyncMock(return_value={})
        inst = _client(
            _request=AsyncMock(return_value=existing),
            push_runner_config=push,
        )
        with patch(SRV, return_value=inst):
            result = runner.invoke(
                cli, ["-s", "http://cp:8022", "server", "remove", "github", "-f"]
            )
        assert result.exit_code == 0, result.output
        assert "github" in result.output
        kwargs = push.call_args.kwargs
        assert "github" not in kwargs["mcp_servers"]
        assert "fs" in kwargs["mcp_servers"]
        # Removal must be a full replace, not additive merge
        assert kwargs["merge"] is False
        # Preserves the existing runner token
        assert kwargs["token"] == "tok"

    def test_remove_unknown_server_exits_1_not_found(self, runner):
        """Removing a server that isn't registered must report it by name.

        DEFECT (expected RED): server.py raises
        ``PlostClientError(404, "Server '...' not found ...")`` but
        ``PlostClientError.__init__(self, message, status_code=None)`` takes the
        message FIRST — so the args are swapped and the user sees "Error: 404"
        instead of the helpful "Server '...' not found" message. Exit code (1)
        is correct; the message is the bug. This assertion encodes the INTENDED
        contract and should stay RED until the arg order is fixed.
        """
        existing = {"mcp_servers": {"fs": {"command": "node"}}, "token": "tok"}
        push = AsyncMock(return_value={})
        inst = _client(
            _request=AsyncMock(return_value=existing),
            push_runner_config=push,
        )
        with patch(SRV, return_value=inst):
            result = runner.invoke(cli, ["-s", "http://cp:8022", "server", "remove", "ghost", "-f"])
        assert result.exit_code == 1
        push.assert_not_called()
        assert "not found" in result.output.lower()  # surfaces arg-swap defect

    def test_remove_runner_missing_exits_1(self, runner):
        """Runner config GET failing must report the runner as not found.

        DEFECT (expected RED): same ``PlostClientError(404, msg)`` arg-order bug
        as above (server.py line 388) — output is "Error: 404" instead of
        "Runner '...' not found".
        """
        inst = _client(
            _request=AsyncMock(side_effect=PlostClientError("boom", status_code=404)),
            push_runner_config=AsyncMock(return_value={}),
        )
        with patch(SRV, return_value=inst):
            result = runner.invoke(
                cli, ["-s", "http://cp:8022", "server", "remove", "github", "-f"]
            )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()  # surfaces arg-swap defect

    def test_remove_without_force_prompts_and_aborts_on_no(self, runner):
        """Interactive confirm declined → abort, no client call."""
        inst = _client(
            _request=AsyncMock(return_value={"mcp_servers": {"github": {}}, "token": "t"}),
            push_runner_config=AsyncMock(return_value={}),
        )
        with patch(SRV, return_value=inst):
            result = runner.invoke(
                cli, ["-s", "http://cp:8022", "server", "remove", "github"], input="n\n"
            )
        assert result.exit_code != 0  # aborted
        inst.push_runner_config.assert_not_called()

    def test_remove_without_force_confirmed_proceeds(self, runner):
        existing = {"mcp_servers": {"github": {"command": "npx"}}, "token": "t"}
        push = AsyncMock(return_value={})
        inst = _client(_request=AsyncMock(return_value=existing), push_runner_config=push)
        with patch(SRV, return_value=inst):
            result = runner.invoke(
                cli, ["-s", "http://cp:8022", "server", "remove", "github"], input="y\n"
            )
        assert result.exit_code == 0, result.output
        push.assert_awaited_once()

    def test_remove_push_failure_exits_1(self, runner):
        existing = {"mcp_servers": {"github": {}, "fs": {}}, "token": "t"}
        inst = _client(
            _request=AsyncMock(return_value=existing),
            push_runner_config=AsyncMock(side_effect=PlostClientError("write failed")),
        )
        with patch(SRV, return_value=inst):
            result = runner.invoke(
                cli, ["-s", "http://cp:8022", "server", "remove", "github", "-f"]
            )
        assert result.exit_code == 1
        assert "write failed" in result.output
