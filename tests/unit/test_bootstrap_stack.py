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
        """Test status with running services including port and health info."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices:\n  ploston:\n    image: test")

            ps_json = (
                '{"Service":"ploston","State":"running","Health":"healthy","Status":"Up 5m (healthy)",'
                '"Publishers":[{"URL":"0.0.0.0","TargetPort":8022,"PublishedPort":8022,"Protocol":"tcp"},'
                '{"URL":"::","TargetPort":8022,"PublishedPort":8022,"Protocol":"tcp"}]}\n'
                '{"Service":"redis","State":"running","Health":"healthy","Status":"Up 5m (healthy)",'
                '"Publishers":[{"URL":"0.0.0.0","TargetPort":6379,"PublishedPort":6379,"Protocol":"tcp"},'
                '{"URL":"::","TargetPort":6379,"PublishedPort":6379,"Protocol":"tcp"}]}\n'
            )

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=ps_json)
                manager = StackManager(compose_dir=Path(tmpdir))
                status = manager.status()

                assert status.state == StackState.RUNNING
                assert len(status.service_details) == 2

                ploston_svc = status.service_details[0]
                assert ploston_svc.name == "ploston"
                assert ploston_svc.health == "healthy"
                assert "8022" in ploston_svc.ports
                # IPv4+IPv6 duplicates should be deduplicated
                assert ploston_svc.ports.count("8022") == 1

    def test_status_service_without_published_ports(self):
        """Test service with no published ports (e.g. internal-only)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yaml"
            compose_file.write_text("version: '3'\nservices:\n  worker:\n    image: test")

            ps_json = (
                '{"Service":"worker","State":"running","Health":"",'
                '"Publishers":[{"URL":"","TargetPort":8081,"PublishedPort":0,"Protocol":"tcp"}]}\n'
            )

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=ps_json)
                manager = StackManager(compose_dir=Path(tmpdir))
                status = manager.status()

                assert status.state == StackState.RUNNING
                worker = status.service_details[0]
                assert worker.ports == []  # PublishedPort=0 means not exposed

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
                # Check that -v flag was passed in the compose down call
                # (first call; subsequent calls are network cleanup)
                compose_call_args = mock_run.call_args_list[0][0][0]
                assert "-v" in compose_call_args

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
