"""Unit tests for bootstrap state module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from ploston_cli.bootstrap import (
    BootstrapAction,
    BootstrapState,
    BootstrapStateManager,
)


class TestBootstrapAction:
    """Tests for BootstrapAction enum."""

    def test_action_values(self):
        """Test all action values exist."""
        assert BootstrapAction.FRESH_INSTALL.value == "fresh_install"
        assert BootstrapAction.KEEP_RUNNING.value == "keep_running"
        assert BootstrapAction.RESTART.value == "restart"
        assert BootstrapAction.RECREATE.value == "recreate"
        assert BootstrapAction.TEARDOWN.value == "teardown"


class TestBootstrapState:
    """Tests for BootstrapState dataclass."""

    def test_fresh_state(self):
        """Test creating a fresh install state."""
        state = BootstrapState(
            has_compose_file=False,
            stack_running=False,
            suggested_action=BootstrapAction.FRESH_INSTALL,
        )
        assert state.has_compose_file is False
        assert state.stack_running is False
        assert state.suggested_action == BootstrapAction.FRESH_INSTALL

    def test_running_state(self):
        """Test creating a running stack state."""
        state = BootstrapState(
            has_compose_file=True,
            stack_running=True,
            running_services=["ploston", "redis"],
            suggested_action=BootstrapAction.KEEP_RUNNING,
        )
        assert state.has_compose_file is True
        assert state.stack_running is True
        assert len(state.running_services) == 2


class TestBootstrapStateManager:
    """Tests for BootstrapStateManager."""

    def test_detect_fresh_install(self):
        """Test detecting fresh install state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("subprocess.run") as mock_run:
                # No running services, no network
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                manager = BootstrapStateManager(base_dir=Path(tmpdir))
                state = manager.detect_state()

            assert state.has_compose_file is False
            assert state.stack_running is False
            assert state.suggested_action == BootstrapAction.FRESH_INSTALL

    def test_detect_existing_compose(self):
        """Test detecting existing compose file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices: {}")

            with patch("subprocess.run") as mock_run:
                # No running services
                mock_run.return_value = MagicMock(returncode=0, stdout="")

                manager = BootstrapStateManager(base_dir=Path(tmpdir))
                state = manager.detect_state()

                assert state.has_compose_file is True

    def test_get_available_actions_fresh(self):
        """Test available actions for fresh install."""
        state = BootstrapState(
            has_compose_file=False,
            stack_running=False,
            suggested_action=BootstrapAction.FRESH_INSTALL,
        )
        manager = BootstrapStateManager()
        actions = manager.get_available_actions(state)

        assert BootstrapAction.FRESH_INSTALL in actions
        assert BootstrapAction.KEEP_RUNNING not in actions

    def test_get_available_actions_running(self):
        """Test available actions for running stack."""
        state = BootstrapState(
            has_compose_file=True,
            stack_running=True,
            running_services=["ploston"],
            suggested_action=BootstrapAction.KEEP_RUNNING,
        )
        manager = BootstrapStateManager()
        actions = manager.get_available_actions(state)

        assert BootstrapAction.KEEP_RUNNING in actions
        assert BootstrapAction.RESTART in actions
        assert BootstrapAction.RECREATE in actions
        assert BootstrapAction.TEARDOWN in actions

    def test_execute_action_teardown(self):
        """Test executing teardown action removes generated files and dirs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            # Generated files
            (base / "docker-compose.yaml").write_text("version: '3'\nservices: {}")
            (base / "ploston-config.yaml").write_text("port: 8022")
            (base / ".env").write_text("FOO=bar")
            (base / ".stack-config").write_text(str(base / "docker-compose.yaml") + "\n")
            # Observability dir (deployed by AssetManager)
            obs = base / "observability" / "prometheus"
            obs.mkdir(parents=True)
            (obs / "prometheus.yml").write_text("global: {}")
            # Stale Docker-created dirs (directories where files should be)
            stale = base / "prometheus" / "prometheus.yml"
            stale.mkdir(parents=True)
            # Redis bind-mount data (should be wiped)
            redis_data = base / "data" / "redis"
            redis_data.mkdir(parents=True)
            (redis_data / "appendonly.aof").write_text("redis-aof-data")
            # User state that must survive
            (base / "runner.pid").write_text("12345")
            (base / "runner.log").write_text("log")
            tokens = base / "tokens"
            tokens.mkdir()
            (tokens / "tok.json").write_text("{}")
            # Other data dirs that should survive
            ploston_data = base / "data" / "ploston"
            ploston_data.mkdir(parents=True, exist_ok=True)
            (ploston_data / "app.db").write_text("")
            # Workflow data that should survive teardown
            workflows_data = base / "data" / "workflows"
            workflows_data.mkdir(parents=True, exist_ok=True)
            (workflows_data / "my-workflow.yaml").write_text("name: my-workflow")

            with (
                patch("subprocess.run") as mock_run,
                patch(
                    "ploston_cli.bootstrap.state.runner_is_running",
                    return_value=(True, 9999),
                ) as mock_is_running,
                patch(
                    "ploston_cli.bootstrap.state.stop_runner",
                ) as mock_stop,
                patch(
                    "ploston_cli.bootstrap.state.inspector_is_running",
                    return_value=(False, None),
                ),
            ):
                mock_run.return_value = MagicMock(returncode=0)

                manager = BootstrapStateManager(base_dir=base)
                success, msg = manager.execute_action(BootstrapAction.TEARDOWN)

                assert success is True
                # Runner daemon stopped before teardown
                mock_is_running.assert_called_once()
                mock_stop.assert_called_once()
                # Generated files removed
                assert not (base / "docker-compose.yaml").exists()
                assert not (base / "ploston-config.yaml").exists()
                assert not (base / ".env").exists()
                assert not (base / ".stack-config").exists()
                # Generated dirs removed
                assert not (base / "observability").exists()
                assert not (base / "prometheus").exists()
                # Redis data wiped
                assert not (base / "data" / "redis").exists()
                # User state preserved
                assert (base / "runner.pid").exists()
                assert (base / "runner.log").exists()
                assert (base / "tokens" / "tok.json").exists()
                # Other data dirs preserved
                assert (base / "data" / "ploston" / "app.db").exists()
                # Workflow data preserved
                assert (base / "data" / "workflows" / "my-workflow.yaml").exists()

    def test_execute_action_teardown_wipes_volumes_when_telemetry_not_preserved(self):
        """Test that teardown passes remove_volumes=True when preserve_telemetry=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "docker-compose.yaml").write_text("version: '3'\nservices: {}")

            with (
                patch("subprocess.run") as mock_run,
                patch(
                    "ploston_cli.bootstrap.state.runner_is_running",
                    return_value=(False, None),
                ),
                patch(
                    "ploston_cli.bootstrap.state.inspector_is_running",
                    return_value=(False, None),
                ),
            ):
                mock_run.return_value = MagicMock(returncode=0)

                manager = BootstrapStateManager(base_dir=base)
                success, msg = manager.execute_action(
                    BootstrapAction.TEARDOWN,
                    preserve_telemetry=False,
                )

                assert success is True
                # Verify docker compose down was called with -v flag
                down_calls = [c for c in mock_run.call_args_list if "down" in str(c)]
                assert len(down_calls) >= 1
                down_args = down_calls[0][0][0]  # first positional arg
                assert "-v" in down_args, (
                    "docker compose down should include -v when preserve_telemetry=False"
                )

    def test_execute_action_teardown_preserves_volumes_by_default(self):
        """Test that teardown does NOT pass -v when preserve_telemetry=True (default)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "docker-compose.yaml").write_text("version: '3'\nservices: {}")

            with (
                patch("subprocess.run") as mock_run,
                patch(
                    "ploston_cli.bootstrap.state.runner_is_running",
                    return_value=(False, None),
                ),
                patch(
                    "ploston_cli.bootstrap.state.inspector_is_running",
                    return_value=(False, None),
                ),
            ):
                mock_run.return_value = MagicMock(returncode=0)

                manager = BootstrapStateManager(base_dir=base)
                success, msg = manager.execute_action(BootstrapAction.TEARDOWN)

                assert success is True
                # Verify docker compose down was called WITHOUT -v flag
                down_calls = [c for c in mock_run.call_args_list if "down" in str(c)]
                assert len(down_calls) >= 1
                down_args = down_calls[0][0][0]
                assert "-v" not in down_args, (
                    "docker compose down should NOT include -v when preserve_telemetry=True"
                )

    def test_execute_action_teardown_stops_inspector_daemon(self):
        """Test that teardown stops a running inspector daemon."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "docker-compose.yaml").write_text("version: '3'\nservices: {}")

            with (
                patch("subprocess.run") as mock_run,
                patch(
                    "ploston_cli.bootstrap.state.runner_is_running",
                    return_value=(False, None),
                ),
                patch(
                    "ploston_cli.bootstrap.state.inspector_is_running",
                    return_value=(True, 7777),
                ) as mock_inspector_alive,
                patch(
                    "ploston_cli.bootstrap.state.stop_inspector",
                ) as mock_stop_inspector,
            ):
                mock_run.return_value = MagicMock(returncode=0)

                manager = BootstrapStateManager(base_dir=base)
                success, _ = manager.execute_action(BootstrapAction.TEARDOWN)

                assert success is True
                mock_inspector_alive.assert_called_once()
                mock_stop_inspector.assert_called_once()

    def test_execute_action_teardown_skips_inspector_when_not_running(self):
        """Test that teardown does not call stop_inspector when not running."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "docker-compose.yaml").write_text("version: '3'\nservices: {}")

            with (
                patch("subprocess.run") as mock_run,
                patch(
                    "ploston_cli.bootstrap.state.runner_is_running",
                    return_value=(False, None),
                ),
                patch(
                    "ploston_cli.bootstrap.state.inspector_is_running",
                    return_value=(False, None),
                ),
                patch(
                    "ploston_cli.bootstrap.state.stop_inspector",
                ) as mock_stop_inspector,
            ):
                mock_run.return_value = MagicMock(returncode=0)

                manager = BootstrapStateManager(base_dir=base)
                success, _ = manager.execute_action(BootstrapAction.TEARDOWN)

                assert success is True
                mock_stop_inspector.assert_not_called()

    def test_execute_action_restart(self):
        """Test executing restart action."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices: {}")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                manager = BootstrapStateManager(base_dir=Path(tmpdir))
                success, msg = manager.execute_action(BootstrapAction.RESTART)

                assert success is True

    def test_execute_action_recreate_pulls_by_default(self):
        """Test RECREATE pulls images before restarting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices: {}")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                manager = BootstrapStateManager(base_dir=Path(tmpdir))
                success, msg = manager.execute_action(BootstrapAction.RECREATE)

                assert success is True
                # Should have called pull (compose pull) then restart (down + up)
                all_args = [c[0][0] for c in mock_run.call_args_list]
                pull_calls = [a for a in all_args if "pull" in a]
                assert len(pull_calls) >= 1, "RECREATE should pull images"

    def test_execute_action_recreate_skip_pull(self):
        """Test RECREATE with skip_pull=True skips the pull step."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices: {}")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                manager = BootstrapStateManager(base_dir=Path(tmpdir))
                success, msg = manager.execute_action(BootstrapAction.RECREATE, skip_pull=True)

                assert success is True
                # Should NOT have called pull — only down + up (restart)
                all_args = [c[0][0] for c in mock_run.call_args_list]
                pull_calls = [a for a in all_args if "pull" in a]
                assert len(pull_calls) == 0, "RECREATE with skip_pull=True should not pull images"

    def test_cleanup(self):
        """Test cleanup removes compose file and data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices: {}")
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            (data_dir / "test.txt").write_text("test")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                manager = BootstrapStateManager(base_dir=Path(tmpdir))
                success, msg = manager.cleanup()

                assert success is True
