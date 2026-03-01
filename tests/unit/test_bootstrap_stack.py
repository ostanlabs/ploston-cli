"""Unit tests for bootstrap stack module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from ploston_cli.bootstrap import StackManager, StackState, StackStatus


class TestStackState:
    """Tests for StackState enum."""

    def test_state_values(self):
        """Test all state values exist."""
        assert StackState.NOT_FOUND.value == "not_found"
        assert StackState.STOPPED.value == "stopped"
        assert StackState.PARTIAL.value == "partial"
        assert StackState.RUNNING.value == "running"
        assert StackState.UNHEALTHY.value == "unhealthy"


class TestStackStatus:
    """Tests for StackStatus dataclass."""

    def test_running_status(self):
        """Test creating a running status."""
        status = StackStatus(
            state=StackState.RUNNING,
            running_services=["ploston", "redis", "native-tools"],
            stopped_services=[],
            message="All services running",
        )
        assert status.state == StackState.RUNNING
        assert len(status.running_services) == 3

    def test_partial_status(self):
        """Test creating a partial status."""
        status = StackStatus(
            state=StackState.PARTIAL,
            running_services=["redis"],
            stopped_services=["ploston", "native-tools"],
            message="Some services stopped",
        )
        assert status.state == StackState.PARTIAL
        assert len(status.running_services) == 1
        assert len(status.stopped_services) == 2


class TestStackManager:
    """Tests for StackManager."""

    def test_default_compose_file(self):
        """Test default compose file path."""
        manager = StackManager()
        assert "docker-compose.yaml" in str(manager.compose_file)

    def test_custom_compose_dir(self):
        """Test custom compose directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices: {}")
            manager = StackManager(compose_dir=Path(tmpdir))
            assert manager.compose_file == compose_file

    def test_status_not_found(self):
        """Test status when compose file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = StackManager(compose_dir=Path(tmpdir))
            status = manager.status()
            assert status.state == StackState.NOT_FOUND

    def test_status_with_running_services(self):
        """Test status with running services."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices:\n  ploston:\n    image: test")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout='{"Service":"ploston","State":"running"}\n{"Service":"redis","State":"running"}\n',
                )
                manager = StackManager(compose_dir=Path(tmpdir))
                status = manager.status()

                assert status.state in [StackState.RUNNING, StackState.PARTIAL]

    def test_up_success(self):
        """Test starting the stack."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices:\n  ploston:\n    image: test")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                manager = StackManager(compose_dir=Path(tmpdir))
                success, msg = manager.up()

                assert success is True
                mock_run.assert_called()

    def test_up_failure(self):
        """Test failed stack start."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices:\n  ploston:\n    image: test")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stderr="Error starting services",
                )
                manager = StackManager(compose_dir=Path(tmpdir))
                success, msg = manager.up()

                assert success is False

    def test_down_success(self):
        """Test stopping the stack."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices:\n  ploston:\n    image: test")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                manager = StackManager(compose_dir=Path(tmpdir))
                success, msg = manager.down()

                assert success is True

    def test_down_with_volumes(self):
        """Test stopping the stack with volume removal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices:\n  ploston:\n    image: test")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                manager = StackManager(compose_dir=Path(tmpdir))
                success, msg = manager.down(remove_volumes=True)

                assert success is True
                # Check that -v flag was passed
                call_args = mock_run.call_args[0][0]
                assert "-v" in call_args

    def test_restart(self):
        """Test restarting the stack."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices:\n  ploston:\n    image: test")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                manager = StackManager(compose_dir=Path(tmpdir))
                success, msg = manager.restart()

                assert success is True

    def test_pull(self):
        """Test pulling images."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices:\n  ploston:\n    image: test")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                manager = StackManager(compose_dir=Path(tmpdir))
                success, msg = manager.pull()

                assert success is True
