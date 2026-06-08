"""Specification-driven tests for `ploston bootstrap` (commands/bootstrap.py).

These tests assert the INTENDED contract of the bootstrap command group and
its subcommands (status / down / logs / restart / restart-runner / rollback /
restore-from-file) plus the flag-parsing / image-resolution / deploy decision
logic in the top-level group.

Boundaries mocked: subprocess-backed managers (StackManager,
BootstrapStateManager, KubectlDeployer, RunnerAutoStart), filesystem-backed
detectors (ConfigDetector, DockerDetector, PortScanner, NetworkManager),
the asyncio entry-point ``_run_bootstrap``, and the daemon helpers. The
command logic itself is exercised through Click's CliRunner.

DISCIPLINE: every assertion encodes the documented/intended behavior — the
constructed argv, exit codes, and user-facing messages — not whatever the
implementation happens to emit. Where the code is observed to deviate from its
contract the test is written to the contract (and would go RED).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

import ploston_cli.commands.bootstrap as bs
from ploston_cli.bootstrap.stack import StackState, StackStatus


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Lightweight stand-ins for the manager/status dataclasses.
# ---------------------------------------------------------------------------


@dataclass
class _Svc:
    name: str
    state: str = "running"
    health: str = ""
    ports: list[str] = field(default_factory=list)
    status: str = ""


# ===========================================================================
# bootstrap status
# ===========================================================================


class TestStatusCommand:
    def test_not_found_prints_hint_and_returns_zero(self, runner):
        """When no stack exists, status prints the bootstrap hint and exits 0."""
        mgr = MagicMock()
        mgr.status.return_value = StackStatus(StackState.NOT_FOUND)
        with (
            patch.object(bs, "StackManager", return_value=mgr),
            patch("ploston_cli.runner.daemon.is_running", return_value=(False, None)),
            patch("ploston_cli.inspector.daemon.is_running", return_value=(False, None)),
        ):
            result = runner.invoke(bs.bootstrap, ["status"])
        assert result.exit_code == 0
        assert "No Ploston stack found" in result.output
        assert "ploston bootstrap" in result.output

    def test_running_renders_service_table_and_endpoints(self, runner):
        """A running stack lists each service with its ports and an Endpoints block."""
        status = StackStatus(
            StackState.RUNNING,
            service_details=[_Svc("ploston", "running", "healthy", ["8022"])],
        )
        mgr = MagicMock()
        mgr.status.return_value = status
        with (
            patch.object(bs, "StackManager", return_value=mgr),
            patch("ploston_cli.runner.daemon.is_running", return_value=(True, 4242)),
            patch("ploston_cli.inspector.daemon.is_running", return_value=(False, None)),
        ):
            result = runner.invoke(bs.bootstrap, ["status"])
        assert result.exit_code == 0
        assert "Stack state: running" in result.output
        assert "ploston" in result.output
        assert ":8022" in result.output
        assert "(healthy)" in result.output
        # Endpoints summary built from running services with ports.
        assert "Endpoints:" in result.output
        assert "http://localhost:8022" in result.output
        # Runner daemon line.
        assert "Runner: running (PID 4242)" in result.output
        assert "Inspector: not running" in result.output

    def test_stopped_service_shows_cross_and_no_endpoint(self, runner):
        """A non-running service is marked with ✗ and contributes no endpoint."""
        status = StackStatus(
            StackState.PARTIAL,
            service_details=[_Svc("redis", "exited", "", ["6379"])],
        )
        mgr = MagicMock()
        mgr.status.return_value = status
        with (
            patch.object(bs, "StackManager", return_value=mgr),
            patch("ploston_cli.runner.daemon.is_running", return_value=(False, None)),
            patch("ploston_cli.inspector.daemon.is_running", return_value=(False, None)),
        ):
            result = runner.invoke(bs.bootstrap, ["status"])
        assert result.exit_code == 0
        assert "✗ redis" in result.output
        # A stopped service must not appear under Endpoints.
        assert "http://localhost:6379" not in result.output
        assert "Runner: not running" in result.output

    def test_inspector_running_renders_bind_url(self, runner):
        """A live inspector daemon prints its PID and formatted bind URL."""
        status = StackStatus(StackState.RUNNING, service_details=[])
        mgr = MagicMock()
        mgr.status.return_value = status
        with (
            patch.object(bs, "StackManager", return_value=mgr),
            patch("ploston_cli.runner.daemon.is_running", return_value=(False, None)),
            patch("ploston_cli.inspector.daemon.is_running", return_value=(True, 999)),
            patch(
                "ploston_cli.inspector.daemon.read_state",
                return_value={"port": 7000, "bind_hosts": ["127.0.0.1"]},
            ),
        ):
            result = runner.invoke(bs.bootstrap, ["status"])
        assert result.exit_code == 0
        assert "Inspector: running (PID 999)" in result.output
        assert "http://127.0.0.1:7000" in result.output


# ===========================================================================
# bootstrap down
# ===========================================================================


class TestDownCommand:
    def test_docker_non_interactive_preserves_telemetry(self, runner):
        """`down -y` tears down preserving telemetry by default (DEC-150)."""
        sm = MagicMock()
        sm.execute_action.return_value = (True, "stopped")
        with (
            patch.object(bs, "_restore_injected_configs"),
            patch.object(bs, "BootstrapStateManager", return_value=sm),
        ):
            result = runner.invoke(bs.bootstrap, ["down", "-y"])
        assert result.exit_code == 0
        assert "✓ Ploston stack stopped." in result.output
        _, kwargs = sm.execute_action.call_args
        assert kwargs["preserve_telemetry"] is True
        assert sm.execute_action.call_args[0][0] is bs.BootstrapAction.TEARDOWN

    def test_docker_volumes_requires_confirmation_and_wipes(self, runner):
        """`down --volumes` confirms, then tears down with preserve_telemetry=False."""
        sm = MagicMock()
        sm.execute_action.return_value = (True, "stopped")
        with (
            patch.object(bs, "_restore_injected_configs"),
            patch.object(bs, "BootstrapStateManager", return_value=sm),
        ):
            result = runner.invoke(bs.bootstrap, ["down", "--volumes"], input="y\n")
        assert result.exit_code == 0
        _, kwargs = sm.execute_action.call_args
        assert kwargs["preserve_telemetry"] is False

    def test_docker_volumes_declined_aborts_without_teardown(self, runner):
        """Declining the destructive confirmation aborts: no teardown is run."""
        sm = MagicMock()
        with (
            patch.object(bs, "_restore_injected_configs"),
            patch.object(bs, "BootstrapStateManager", return_value=sm),
        ):
            result = runner.invoke(bs.bootstrap, ["down", "--volumes"], input="n\n")
        assert result.exit_code == 0
        sm.execute_action.assert_not_called()

    def test_docker_failure_exits_nonzero(self, runner):
        """A teardown failure surfaces the message on stderr and exits 1."""
        sm = MagicMock()
        sm.execute_action.return_value = (False, "boom")
        with (
            patch.object(bs, "_restore_injected_configs"),
            patch.object(bs, "BootstrapStateManager", return_value=sm),
        ):
            result = runner.invoke(bs.bootstrap, ["down", "-y"])
        assert result.exit_code == 1
        assert "boom" in result.output

    def test_k8s_target_deletes_namespace(self, runner):
        """`down --target k8s` deletes the namespace via KubectlDeployer."""
        dep = MagicMock()
        dep.delete_namespace.return_value = (True, "deleted")
        with (
            patch.object(bs, "_restore_injected_configs"),
            patch.object(bs, "KubectlDeployer", return_value=dep) as kd_mock,
        ):
            result = runner.invoke(
                bs.bootstrap,
                ["down", "--target", "k8s", "--namespace", "myns", "--kubeconfig", "/kc"],
            )
        assert result.exit_code == 0
        kd_mock.assert_called_once_with("/kc")
        dep.delete_namespace.assert_called_once_with("myns")
        assert "deleted" in result.output

    def test_k8s_failure_exits_nonzero(self, runner):
        dep = MagicMock()
        dep.delete_namespace.return_value = (False, "no cluster")
        with (
            patch.object(bs, "_restore_injected_configs"),
            patch.object(bs, "KubectlDeployer", return_value=dep),
        ):
            result = runner.invoke(bs.bootstrap, ["down", "--target", "k8s"])
        assert result.exit_code == 1
        assert "no cluster" in result.output


# ===========================================================================
# bootstrap logs
# ===========================================================================


class TestLogsCommand:
    def test_logs_passes_flags_through_and_waits(self, runner):
        """`logs -f -s ploston --tail 50` forwards flags and waits on the proc."""
        proc = MagicMock()
        mgr = MagicMock()
        mgr.logs.return_value = proc
        with patch.object(bs, "StackManager", return_value=mgr):
            result = runner.invoke(bs.bootstrap, ["logs", "-f", "-s", "ploston", "--tail", "50"])
        assert result.exit_code == 0
        mgr.logs.assert_called_once_with(follow=True, service="ploston", tail=50)
        proc.wait.assert_called_once()

    def test_logs_none_proc_is_noop(self, runner):
        """When logs() returns None (no stack) the command is a clean no-op."""
        mgr = MagicMock()
        mgr.logs.return_value = None
        with patch.object(bs, "StackManager", return_value=mgr):
            result = runner.invoke(bs.bootstrap, ["logs"])
        assert result.exit_code == 0
        mgr.logs.assert_called_once_with(follow=False, service=None, tail=100)

    def test_logs_keyboard_interrupt_terminates_proc(self, runner):
        """Ctrl-C during follow terminates and reaps the child process."""
        proc = MagicMock()
        proc.wait.side_effect = [KeyboardInterrupt, None]
        mgr = MagicMock()
        mgr.logs.return_value = proc
        with patch.object(bs, "StackManager", return_value=mgr):
            result = runner.invoke(bs.bootstrap, ["logs", "-f"])
        assert result.exit_code == 0
        proc.terminate.assert_called_once()
        assert proc.wait.call_count == 2


# ===========================================================================
# bootstrap restart
# ===========================================================================


class TestRestartCommand:
    def test_success(self, runner):
        mgr = MagicMock()
        mgr.restart.return_value = (True, "ok")
        with patch.object(bs, "StackManager", return_value=mgr):
            result = runner.invoke(bs.bootstrap, ["restart"])
        assert result.exit_code == 0
        assert "✓ Stack restarted." in result.output

    def test_failure_exits_one(self, runner):
        mgr = MagicMock()
        mgr.restart.return_value = (False, "nope")
        with patch.object(bs, "StackManager", return_value=mgr):
            result = runner.invoke(bs.bootstrap, ["restart"])
        assert result.exit_code == 1
        assert "nope" in result.output


# ===========================================================================
# bootstrap restart-runner
# ===========================================================================


class TestRestartRunnerCommand:
    def test_no_token_aborts_with_exit_one(self, runner):
        """Missing runner token → error message + exit 1, no start attempted."""
        runner_obj = MagicMock()
        runner_obj._get_runner_token.return_value = None
        with (
            patch("ploston_cli.runner.daemon.is_running", return_value=(False, None)),
            patch("ploston_cli.runner.daemon.stop_daemon"),
            patch.object(bs, "RunnerAutoStart", return_value=runner_obj),
        ):
            result = runner.invoke(bs.bootstrap, ["restart-runner"])
        assert result.exit_code == 1
        assert "Runner token not found" in result.output
        runner_obj.start_runner.assert_not_called()

    def test_stops_then_starts_when_running(self, runner):
        """When the runner is alive it is stopped, then restarted as a daemon."""
        runner_obj = MagicMock()
        runner_obj._get_runner_token.return_value = "plt_x"
        runner_obj._get_runner_name.return_value = "host-1"
        runner_obj._get_ws_url.return_value = "ws://localhost:8022/api/v1/runner/ws"
        runner_obj.start_runner.return_value = (True, "started")
        with (
            patch("ploston_cli.runner.daemon.is_running", return_value=(True, 77)),
            patch("ploston_cli.runner.daemon.stop_daemon") as stop,
            patch.object(bs, "RunnerAutoStart", return_value=runner_obj),
        ):
            result = runner.invoke(bs.bootstrap, ["restart-runner"])
        assert result.exit_code == 0
        stop.assert_called_once()
        runner_obj.start_runner.assert_called_once_with(daemon=True)
        assert "Stopping runner (PID 77)" in result.output
        assert "✓ Runner restarted" in result.output

    def test_start_failure_exits_one(self, runner):
        runner_obj = MagicMock()
        runner_obj._get_runner_token.return_value = "plt_x"
        runner_obj._get_runner_name.return_value = "host-1"
        runner_obj._get_ws_url.return_value = "ws://x"
        runner_obj.start_runner.return_value = (False, "spawn failed")
        with (
            patch("ploston_cli.runner.daemon.is_running", return_value=(False, None)),
            patch("ploston_cli.runner.daemon.stop_daemon"),
            patch.object(bs, "RunnerAutoStart", return_value=runner_obj),
        ):
            result = runner.invoke(bs.bootstrap, ["restart-runner"])
        assert result.exit_code == 1
        assert "spawn failed" in result.output


# ===========================================================================
# bootstrap rollback
# ===========================================================================


def _cfg(path: Path, source: str = "cursor"):
    c = MagicMock()
    c.path = path
    c.source = source
    return c


class TestRollbackCommand:
    def test_no_injected_configs_reports_nothing_to_do(self, runner, tmp_path):
        """With no injected configs, rollback reports a no-op."""
        det = MagicMock()
        det.detect_all.return_value = []
        with patch.object(bs, "ConfigDetector", return_value=det):
            result = runner.invoke(bs.bootstrap, ["rollback"])
        assert result.exit_code == 0
        assert "nothing to roll back" in result.output

    def test_restores_from_imported(self, runner, tmp_path):
        """An injected config restorable from _ploston_imported is counted."""
        p = tmp_path / "mcp.json"
        p.write_text("{}")
        det = MagicMock()
        det.detect_all.return_value = [_cfg(p)]
        with (
            patch.object(bs, "ConfigDetector", return_value=det),
            patch.object(bs, "is_already_injected", return_value=True),
            patch.object(bs, "restore_config_from_imported", return_value=True),
        ):
            result = runner.invoke(bs.bootstrap, ["rollback"])
        assert result.exit_code == 0
        assert "1 config(s) restored" in result.output

    def test_falls_back_to_layer2_backup(self, runner, tmp_path):
        """When _ploston_imported restore fails, fall back to file backup."""
        p = tmp_path / "mcp.json"
        p.write_text("{}")
        det = MagicMock()
        det.detect_all.return_value = [_cfg(p)]
        with (
            patch.object(bs, "ConfigDetector", return_value=det),
            patch.object(bs, "is_already_injected", return_value=True),
            patch.object(bs, "restore_config_from_imported", return_value=False),
            patch.object(bs, "restore_from_backup", return_value=True),
        ):
            result = runner.invoke(bs.bootstrap, ["rollback"])
        assert result.exit_code == 0
        assert "Layer-2 file backup" in result.output
        assert "1 config(s) restored" in result.output

    def test_unrestorable_config_warns_but_exits_zero(self, runner, tmp_path):
        """A config that cannot be restored warns; restored count stays 0."""
        p = tmp_path / "mcp.json"
        p.write_text("{}")
        det = MagicMock()
        det.detect_all.return_value = [_cfg(p)]
        with (
            patch.object(bs, "ConfigDetector", return_value=det),
            patch.object(bs, "is_already_injected", return_value=True),
            patch.object(bs, "restore_config_from_imported", return_value=False),
            patch.object(bs, "restore_from_backup", return_value=False),
        ):
            result = runner.invoke(bs.bootstrap, ["rollback"])
        assert result.exit_code == 0
        assert "could not be restored" in result.output
        assert "restored" not in result.output.split("could not be restored")[1]


# ===========================================================================
# bootstrap restore-from-file
# ===========================================================================


class TestRestoreFromFileCommand:
    def test_unknown_target_exits_one(self, runner):
        """An unregistered target id errors and exits 1."""
        with patch.dict(
            "ploston_cli.init.injection_targets.registry.TARGET_REGISTRY",
            {},
            clear=True,
        ):
            result = runner.invoke(bs.bootstrap, ["restore-from-file", "--target", "nope"])
        assert result.exit_code == 1
        assert "Unknown target: nope" in result.output

    def test_missing_config_exits_one(self, runner, tmp_path):
        """When the target has no config file present, exit 1."""
        target = MagicMock()
        target.detect.return_value = None
        with patch.dict(
            "ploston_cli.init.injection_targets.registry.TARGET_REGISTRY",
            {"cursor": target},
            clear=True,
        ):
            result = runner.invoke(bs.bootstrap, ["restore-from-file", "--target", "cursor"])
        assert result.exit_code == 1
        assert "No config file found" in result.output

    def test_no_backup_returns_zero(self, runner, tmp_path):
        """A present config with no backup returns 0 with an informational note."""
        cfg = tmp_path / "mcp.json"
        cfg.write_text("{}")
        target = MagicMock()
        target.detect.return_value = cfg
        with (
            patch.dict(
                "ploston_cli.init.injection_targets.registry.TARGET_REGISTRY",
                {"cursor": target},
                clear=True,
            ),
            patch.object(bs, "find_latest_backup", return_value=None),
        ):
            result = runner.invoke(bs.bootstrap, ["restore-from-file", "--target", "cursor"])
        assert result.exit_code == 0
        assert "No Layer-2 backup found" in result.output

    def test_confirmed_restore_succeeds(self, runner, tmp_path):
        cfg = tmp_path / "mcp.json"
        cfg.write_text("{}")
        backup = tmp_path / "mcp.json.ploston-backup-x"
        backup.write_text("{}")
        target = MagicMock()
        target.detect.return_value = cfg
        with (
            patch.dict(
                "ploston_cli.init.injection_targets.registry.TARGET_REGISTRY",
                {"cursor": target},
                clear=True,
            ),
            patch.object(bs, "find_latest_backup", return_value=backup),
            patch.object(bs, "restore_from_backup", return_value=True),
        ):
            result = runner.invoke(
                bs.bootstrap, ["restore-from-file", "--target", "cursor"], input="y\n"
            )
        assert result.exit_code == 0
        assert "✓ Restored" in result.output

    def test_declined_restore_aborts(self, runner, tmp_path):
        cfg = tmp_path / "mcp.json"
        cfg.write_text("{}")
        backup = tmp_path / "bk"
        backup.write_text("{}")
        target = MagicMock()
        target.detect.return_value = cfg
        with (
            patch.dict(
                "ploston_cli.init.injection_targets.registry.TARGET_REGISTRY",
                {"cursor": target},
                clear=True,
            ),
            patch.object(bs, "find_latest_backup", return_value=backup),
            patch.object(bs, "restore_from_backup") as rfb,
        ):
            result = runner.invoke(
                bs.bootstrap, ["restore-from-file", "--target", "cursor"], input="n\n"
            )
        assert result.exit_code == 0
        assert "Aborted." in result.output
        rfb.assert_not_called()

    def test_restore_failure_exits_one(self, runner, tmp_path):
        cfg = tmp_path / "mcp.json"
        cfg.write_text("{}")
        backup = tmp_path / "bk"
        backup.write_text("{}")
        target = MagicMock()
        target.detect.return_value = cfg
        with (
            patch.dict(
                "ploston_cli.init.injection_targets.registry.TARGET_REGISTRY",
                {"cursor": target},
                clear=True,
            ),
            patch.object(bs, "find_latest_backup", return_value=backup),
            patch.object(bs, "restore_from_backup", return_value=False),
        ):
            result = runner.invoke(
                bs.bootstrap, ["restore-from-file", "--target", "cursor"], input="y\n"
            )
        assert result.exit_code == 1
        assert "Failed to restore" in result.output


# ===========================================================================
# Top-level group: flag parsing & image resolution
# ===========================================================================


@dataclass
class _Img:
    ploston_image: str = "ghcr.io/ostanlabs/ploston:latest"
    native_tools_image: str = "ghcr.io/ostanlabs/native-tools:latest"
    build_from_source: bool = False
    should_pull: bool = True


class TestGroupFlagParsing:
    def test_default_resolves_release_images_and_runs(self, runner):
        """No flags → resolve_images called with all-false, then _run_bootstrap."""
        img = _Img()
        with (
            patch.object(bs, "resolve_images", return_value=img) as ri,
            patch.object(bs, "_run_bootstrap", new=MagicMock(return_value=None)),
            patch.object(bs, "asyncio") as aio,
        ):
            result = runner.invoke(bs.bootstrap, [])
        assert result.exit_code == 0
        ri.assert_called_once_with(image_tag=None, edge=False, build_from_source=False)
        aio.run.assert_called_once()

    def test_edge_flag_forwarded_to_resolver(self, runner):
        img = _Img()
        with (
            patch.object(bs, "resolve_images", return_value=img) as ri,
            patch.object(bs, "_run_bootstrap", new=MagicMock(return_value=None)),
            patch.object(bs, "asyncio"),
        ):
            runner.invoke(bs.bootstrap, ["--edge"])
        _, kwargs = ri.call_args
        assert kwargs["edge"] is True

    def test_pre_release_alias_warns_and_sets_edge(self, runner):
        """--pre-release is a deprecated alias: warns on stderr and enables edge."""
        img = _Img()
        with (
            patch.object(bs, "resolve_images", return_value=img) as ri,
            patch.object(bs, "_run_bootstrap", new=MagicMock(return_value=None)),
            patch.object(bs, "asyncio"),
        ):
            result = runner.invoke(bs.bootstrap, ["--pre-release"])
        assert "--pre-release is deprecated" in result.output
        _, kwargs = ri.call_args
        assert kwargs["edge"] is True

    def test_image_tag_forwarded(self, runner):
        img = _Img()
        with (
            patch.object(bs, "resolve_images", return_value=img) as ri,
            patch.object(bs, "_run_bootstrap", new=MagicMock(return_value=None)),
            patch.object(bs, "asyncio"),
        ):
            runner.invoke(bs.bootstrap, ["--image-tag", "sha-abc1234"])
        _, kwargs = ri.call_args
        assert kwargs["image_tag"] == "sha-abc1234"

    def test_resolver_error_exits_one(self, runner):
        """Mutually exclusive flags surface ImageResolverError on stderr, exit 1."""
        with patch.object(bs, "resolve_images", side_effect=bs.ImageResolverError("bad combo")):
            result = runner.invoke(bs.bootstrap, ["--build-from-source", "--edge"])
        assert result.exit_code == 1
        assert "Error: bad combo" in result.output

    def test_run_bootstrap_receives_observability_and_target(self, runner):
        """--with-observability/--target/-y are threaded into _run_bootstrap."""
        img = _Img()
        captured = {}

        async def fake_run(**kwargs):
            captured.update(kwargs)
            return bs.BootstrapResult(success=True)

        with (
            patch.object(bs, "resolve_images", return_value=img),
            patch.object(bs, "_run_bootstrap", side_effect=fake_run),
        ):
            result = runner.invoke(
                bs.bootstrap,
                ["--with-observability", "--target", "k8s", "-y", "--namespace", "ns2"],
            )
        assert result.exit_code == 0
        assert captured["with_observability"] is True
        assert captured["target"] == "k8s"
        assert captured["non_interactive"] is True
        assert captured["namespace"] == "ns2"

    def test_no_import_flag_threaded_as_skip_import(self, runner):
        img = _Img()
        captured = {}

        async def fake_run(**kwargs):
            captured.update(kwargs)
            return bs.BootstrapResult(success=True)

        with (
            patch.object(bs, "resolve_images", return_value=img),
            patch.object(bs, "_run_bootstrap", side_effect=fake_run),
        ):
            runner.invoke(bs.bootstrap, ["--no-import"])
        assert captured["skip_import"] is True

    def test_invoking_subcommand_does_not_run_bootstrap(self, runner):
        """Passing a subcommand must not trigger image resolution / deploy."""
        mgr = MagicMock()
        mgr.status.return_value = StackStatus(StackState.NOT_FOUND)
        with (
            patch.object(bs, "resolve_images") as ri,
            patch.object(bs, "asyncio") as aio,
            patch.object(bs, "StackManager", return_value=mgr),
            patch("ploston_cli.runner.daemon.is_running", return_value=(False, None)),
            patch("ploston_cli.inspector.daemon.is_running", return_value=(False, None)),
        ):
            result = runner.invoke(bs.bootstrap, ["status"])
        assert result.exit_code == 0
        ri.assert_not_called()
        aio.run.assert_not_called()


# ===========================================================================
# Module helpers: _prompt_preserve_telemetry / _handle_network_conflict
# ===========================================================================


class TestPromptPreserveTelemetry:
    def test_default_yes_preserves(self):
        with patch.object(bs.click, "prompt", return_value="Y"):
            assert bs._prompt_preserve_telemetry() is True

    def test_no_wipes(self):
        with patch.object(bs.click, "prompt", return_value="n"):
            assert bs._prompt_preserve_telemetry() is False

    def test_no_word_wipes(self):
        with patch.object(bs.click, "prompt", return_value="no"):
            assert bs._prompt_preserve_telemetry() is False


class TestHandleNetworkConflict:
    def test_no_conflict_proceeds_internal(self):
        nm = MagicMock()
        nm.check_network_exists.return_value = MagicMock(exists=False)
        with patch.object(bs, "NetworkManager", return_value=nm):
            res = bs._handle_network_conflict("net", non_interactive=True)
        assert res.proceed is True
        assert res.network_name == "net"
        assert res.network_external is False

    def test_existing_network_non_interactive_uses_external(self):
        nm = MagicMock()
        nm.check_network_exists.return_value = MagicMock(exists=True, network_info=None)
        nm.check_service_conflicts.return_value = []
        with patch.object(bs, "NetworkManager", return_value=nm):
            res = bs._handle_network_conflict("net", non_interactive=True)
        assert res.proceed is True
        assert res.network_external is True

    def test_interactive_choice_4_cancels(self, runner):
        nm = MagicMock()
        nm.check_network_exists.return_value = MagicMock(exists=True, network_info=None)
        nm.check_service_conflicts.return_value = []
        nm.suggest_alternative_name.return_value = "ploston-network-2"
        with (
            patch.object(bs, "NetworkManager", return_value=nm),
            patch.object(bs.click, "prompt", return_value="4"),
        ):
            res = bs._handle_network_conflict("net", non_interactive=False)
        assert res.proceed is False
        assert res.error == "Cancelled by user"

    def test_interactive_choice_3_uses_alternative_name(self):
        nm = MagicMock()
        nm.check_network_exists.return_value = MagicMock(exists=True, network_info=None)
        nm.check_service_conflicts.return_value = []
        nm.suggest_alternative_name.return_value = "ploston-network-2"
        with (
            patch.object(bs, "NetworkManager", return_value=nm),
            patch.object(bs.click, "prompt", return_value="3"),
        ):
            res = bs._handle_network_conflict("net", non_interactive=False)
        assert res.proceed is True
        assert res.network_name == "ploston-network-2"
        assert res.network_external is False

    def test_interactive_choice_1_removes_network(self):
        nm = MagicMock()
        nm.check_network_exists.return_value = MagicMock(exists=True, network_info=None)
        nm.check_service_conflicts.return_value = []
        nm.suggest_alternative_name.return_value = "alt"
        nm.remove_network.return_value = (True, "removed")
        with (
            patch.object(bs, "NetworkManager", return_value=nm),
            patch.object(bs.click, "prompt", return_value="1"),
        ):
            res = bs._handle_network_conflict("net", non_interactive=False)
        assert res.proceed is True
        assert res.network_external is False
        nm.remove_network.assert_called_once_with(force=True)

    def test_interactive_choice_1_remove_failure(self):
        nm = MagicMock()
        nm.check_network_exists.return_value = MagicMock(exists=True, network_info=None)
        nm.check_service_conflicts.return_value = []
        nm.suggest_alternative_name.return_value = "alt"
        nm.remove_network.return_value = (False, "in use")
        with (
            patch.object(bs, "NetworkManager", return_value=nm),
            patch.object(bs.click, "prompt", return_value="1"),
        ):
            res = bs._handle_network_conflict("net", non_interactive=False)
        assert res.proceed is False
        assert res.error == "in use"
