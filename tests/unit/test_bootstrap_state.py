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
        """Test executing teardown action."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices: {}")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                manager = BootstrapStateManager(base_dir=Path(tmpdir))
                success, msg = manager.execute_action(BootstrapAction.TEARDOWN)

                assert success is True

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
