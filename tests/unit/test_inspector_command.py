"""Unit tests for the ``ploston inspector`` click group and subcommands.

Covers the command-routing logic (smart default, status, stop, logs) and the
non-fork branches of ``inspector start`` (already-running detection, token
persistence/load). The actual fork-and-detach path is integration territory
and is not exercised here.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ploston_cli.commands import inspector as inspector_cmd


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.mark.cli_unit
class TestStatusCommand:
    def test_status_when_not_running(self, runner: CliRunner):
        with patch.object(inspector_cmd.inspector_daemon, "is_running", return_value=(False, None)):
            result = runner.invoke(inspector_cmd.inspector_command, ["status"])
        assert result.exit_code == 0
        assert "Inspector: not running" in result.output

    def test_status_when_running(self, runner: CliRunner):
        with (
            patch.object(inspector_cmd.inspector_daemon, "is_running", return_value=(True, 12345)),
            patch.object(inspector_cmd.inspector_daemon, "read_state", return_value=None),
        ):
            result = runner.invoke(inspector_cmd.inspector_command, ["status"])
        assert result.exit_code == 0
        assert "Inspector: running" in result.output
        assert "12345" in result.output

    def test_status_shows_url_from_state(self, runner: CliRunner):
        state = {
            "host": "127.0.0.1",
            "bind_hosts": ["127.0.0.1", "::1"],
            "port": 7777,
            "url": "http://localhost:8022",
        }
        with (
            patch.object(inspector_cmd.inspector_daemon, "is_running", return_value=(True, 9999)),
            patch.object(inspector_cmd.inspector_daemon, "read_state", return_value=state),
        ):
            result = runner.invoke(inspector_cmd.inspector_command, ["status"])
        assert result.exit_code == 0
        assert "URL: http://127.0.0.1:7777" in result.output
        assert "http://[::1]:7777" in result.output
        assert "CP:  http://localhost:8022" in result.output

    def test_status_legacy_state_without_bind_hosts(self, runner: CliRunner):
        # Pre-dual-stack daemons wrote only ``host``; the status command must
        # still surface a single URL line for backward compatibility.
        state = {"host": "127.0.0.1", "port": 7777, "url": "http://localhost:8022"}
        with (
            patch.object(inspector_cmd.inspector_daemon, "is_running", return_value=(True, 9999)),
            patch.object(inspector_cmd.inspector_daemon, "read_state", return_value=state),
        ):
            result = runner.invoke(inspector_cmd.inspector_command, ["status"])
        assert result.exit_code == 0
        assert "URL: http://127.0.0.1:7777" in result.output
        assert "[::1]" not in result.output

    def test_status_running_without_state_omits_url(self, runner: CliRunner):
        with (
            patch.object(inspector_cmd.inspector_daemon, "is_running", return_value=(True, 9999)),
            patch.object(inspector_cmd.inspector_daemon, "read_state", return_value=None),
        ):
            result = runner.invoke(inspector_cmd.inspector_command, ["status"])
        assert result.exit_code == 0
        assert "Inspector: running" in result.output
        assert "URL:" not in result.output


@pytest.mark.cli_unit
class TestStopCommand:
    def test_stop_invokes_daemon_with_token_cleanup(self, runner: CliRunner):
        with patch.object(inspector_cmd.inspector_daemon, "stop_daemon") as mock_stop:
            result = runner.invoke(inspector_cmd.inspector_command, ["stop"])
        assert result.exit_code == 0
        mock_stop.assert_called_once()
        kwargs = mock_stop.call_args.kwargs
        assert callable(kwargs["on_stopped"])


@pytest.mark.cli_unit
class TestLogsCommand:
    def test_logs_when_no_log_file(self, runner: CliRunner, tmp_path: Path):
        nonexistent = tmp_path / "missing.log"
        with patch.object(inspector_cmd, "INSPECTOR_LOG_FILE", nonexistent):
            result = runner.invoke(inspector_cmd.inspector_command, ["logs"])
        assert result.exit_code == 0
        assert "No log file found" in result.output

    def test_logs_invokes_tail(self, runner: CliRunner, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_file.write_text("hello\n")
        with (
            patch.object(inspector_cmd, "INSPECTOR_LOG_FILE", log_file),
            patch.object(inspector_cmd.subprocess, "run") as mock_run,
        ):
            result = runner.invoke(inspector_cmd.inspector_command, ["logs", "-n", "10"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        args = mock_run.call_args.args[0]
        assert args[0] == "tail"
        assert "10" in args
        assert str(log_file) in args


@pytest.mark.cli_unit
class TestStartCommandAlreadyRunning:
    def test_start_daemon_with_existing_daemon_opens_browser(self, runner: CliRunner):
        with (
            patch.object(inspector_cmd.inspector_daemon, "is_running", return_value=(True, 12345)),
            patch.object(inspector_cmd.webbrowser, "open") as mock_open,
        ):
            result = runner.invoke(inspector_cmd.inspector_command, ["start"])
        assert result.exit_code == 0
        assert "already running" in result.output
        # User-facing URL should be ``localhost``, not the bind literal.
        assert "http://localhost:7777" in result.output
        assert "127.0.0.1:7777" not in result.output
        # Cache-busting ``?t=<epoch>`` query string defeats Chrome's tab-
        # reuse heuristic so a stop/start cycle force-navigates the tab.
        mock_open.assert_called_once()
        opened_url = mock_open.call_args.args[0]
        assert opened_url.startswith("http://localhost:7777/?t=")

    def test_foreground_refuses_when_daemon_alive(self, runner: CliRunner):
        with patch.object(inspector_cmd.inspector_daemon, "is_running", return_value=(True, 12345)):
            result = runner.invoke(inspector_cmd.inspector_command, ["start", "--foreground"])
        assert result.exit_code == 1
        assert "already running" in result.output


@pytest.mark.cli_unit
class TestStartCommandTokenPersistence:
    def test_explicit_token_is_persisted_when_starting_daemon(
        self, runner: CliRunner, tmp_path: Path
    ):
        token_file = tmp_path / "tokens" / "inspector.token"
        with (
            patch.object(inspector_cmd.inspector_daemon, "is_running", return_value=(False, None)),
            patch.object(inspector_cmd.inspector_daemon, "start_daemon") as mock_start,
            patch.object(inspector_cmd, "get_token_file", return_value=token_file),
        ):
            result = runner.invoke(
                inspector_cmd.inspector_command,
                ["start", "--token", "abc123", "--no-open"],
            )
        # The patched start_daemon does nothing, so control returns from the
        # parent path immediately.
        assert result.exit_code == 0
        assert token_file.exists()
        assert token_file.read_text() == "abc123"
        # Mode should be locked down to 0o600.
        assert oct(token_file.stat().st_mode)[-3:] == "600"
        mock_start.assert_called_once()


@pytest.mark.cli_unit
class TestSmartDefault:
    def test_bare_invocation_routes_to_start(self, runner: CliRunner):
        # When no subcommand is given, the group should call ``start_command``.
        with (
            patch.object(inspector_cmd.inspector_daemon, "is_running", return_value=(True, 999)),
            patch.object(inspector_cmd.webbrowser, "open"),
        ):
            result = runner.invoke(inspector_cmd.inspector_command, [])
        assert result.exit_code == 0
        assert "already running" in result.output


@pytest.mark.cli_unit
class TestResolveBindHosts:
    """``resolve_bind_hosts`` decides whether to dual-stack the inspector.

    Default loopback expands to both IPv4 and IPv6 so Chrome's IPv6-first
    ``localhost`` resolution does not refuse the connection. Explicit
    operator intent (``0.0.0.0``, ``::``, a routable IP) is preserved.
    """

    def test_127_loopback_expands_to_both_stacks(self):
        from ploston_cli.inspector.server import resolve_bind_hosts

        assert resolve_bind_hosts("127.0.0.1") == ["127.0.0.1", "::1"]

    def test_localhost_expands_to_both_stacks(self):
        from ploston_cli.inspector.server import resolve_bind_hosts

        assert resolve_bind_hosts("localhost") == ["127.0.0.1", "::1"]

    def test_explicit_host_is_preserved(self):
        from ploston_cli.inspector.server import resolve_bind_hosts

        assert resolve_bind_hosts("0.0.0.0") == ["0.0.0.0"]
        assert resolve_bind_hosts("::") == ["::"]
        assert resolve_bind_hosts("10.0.0.5") == ["10.0.0.5"]


@pytest.mark.cli_unit
class TestFormatBindUrl:
    def test_ipv4_unbracketed(self):
        assert inspector_cmd._format_bind_url("127.0.0.1", 7777) == "http://127.0.0.1:7777"

    def test_ipv6_bracketed(self):
        assert inspector_cmd._format_bind_url("::1", 7777) == "http://[::1]:7777"


@pytest.mark.cli_unit
class TestDisplayHost:
    """Browser/echo URL maps loopback literals to ``localhost``.

    Operators paste these URLs into chats, docs, and curl commands; raw
    ``127.0.0.1`` carries no useful information beyond what ``localhost``
    already conveys, and ``localhost`` works in every browser regardless of
    IPv4/IPv6 resolution preference (the daemon dual-binds both stacks).
    """

    @pytest.mark.parametrize("host", ["127.0.0.1", "::1", "0.0.0.0", "::"])
    def test_loopback_and_wildcards_become_localhost(self, host: str):
        assert inspector_cmd._display_host(host) == "localhost"

    def test_explicit_host_is_preserved(self):
        assert inspector_cmd._display_host("10.0.0.5") == "10.0.0.5"
        assert inspector_cmd._display_host("inspector.local") == "inspector.local"

    def test_open_browser_uses_localhost_for_loopback(self):
        with patch.object(inspector_cmd.webbrowser, "open") as mock_open:
            inspector_cmd._open_browser_if_requested(True, "127.0.0.1", 7777)
        mock_open.assert_called_once()
        opened_url = mock_open.call_args.args[0]
        # ``localhost``, not the bind literal, plus a ``?t=<epoch>`` cache-
        # buster so Chrome doesn't reuse a stale tab from a previous
        # start/stop cycle.
        assert opened_url.startswith("http://localhost:7777/?t=")
        # Token must be a positive integer (epoch seconds).
        token = opened_url.rsplit("=", 1)[1]
        assert token.isdigit() and int(token) > 0
