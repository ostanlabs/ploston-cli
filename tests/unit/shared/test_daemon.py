"""Unit tests for the shared daemon scaffolding.

Focuses on the parts of :mod:`ploston_cli.shared.daemon` that can be exercised
without forking: PID-file life cycle, stale PID recovery, log-tail helper,
and ``DaemonSpec`` construction.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ploston_cli.shared import daemon as daemon_module


@pytest.fixture
def spec(tmp_path: Path) -> daemon_module.DaemonSpec:
    return daemon_module.DaemonSpec(
        name="testd",
        pid_file=tmp_path / "test.pid",
        log_file=tmp_path / "test.log",
    )


@pytest.mark.cli_unit
class TestIsRunning:
    def test_no_pid_file(self, spec):
        assert daemon_module.is_running(spec) == (False, None)

    def test_invalid_pid_file_is_cleaned_up(self, spec):
        spec.pid_file.write_text("not-an-int")
        assert daemon_module.is_running(spec) == (False, None)
        assert not spec.pid_file.exists()

    def test_stale_pid_file_is_cleaned_up(self, spec):
        # PID 999999 is almost certainly not a real process.
        spec.pid_file.write_text("999999")
        with patch("os.kill", side_effect=ProcessLookupError):
            alive, pid = daemon_module.is_running(spec)
        assert (alive, pid) == (False, None)
        assert not spec.pid_file.exists()

    def test_running_when_signal_zero_succeeds(self, spec):
        spec.pid_file.write_text(str(os.getpid()))
        with patch("os.kill", return_value=None) as mock_kill:
            alive, pid = daemon_module.is_running(spec)
        assert alive is True
        assert pid == os.getpid()
        mock_kill.assert_called_once_with(os.getpid(), 0)

    def test_running_when_permission_error(self, spec):
        spec.pid_file.write_text("12345")
        with patch("os.kill", side_effect=PermissionError):
            alive, pid = daemon_module.is_running(spec)
        assert alive is True
        assert pid == 12345


@pytest.mark.cli_unit
class TestGetPid:
    def test_returns_pid_when_running(self, spec):
        spec.pid_file.write_text("12345")
        with patch("os.kill", return_value=None):
            assert daemon_module.get_pid(spec) == 12345

    def test_returns_none_when_not_running(self, spec):
        assert daemon_module.get_pid(spec) is None


@pytest.mark.cli_unit
class TestTailLines:
    def test_empty_file_returns_empty(self, tmp_path: Path):
        log_file = tmp_path / "empty.log"
        log_file.write_text("")
        assert daemon_module._tail_lines(log_file, n=5) == ""

    def test_returns_last_n_lines(self, tmp_path: Path):
        log_file = tmp_path / "t.log"
        log_file.write_text("\n".join(f"line-{i}" for i in range(10)) + "\n")
        result = daemon_module._tail_lines(log_file, n=3)
        assert result.splitlines() == ["line-7", "line-8", "line-9"]

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert daemon_module._tail_lines(tmp_path / "nope.log", n=3) == ""


@pytest.mark.cli_unit
class TestStopDaemon:
    def test_no_daemon_running_prints_friendly_message(self, spec, capsys):
        daemon_module.stop_daemon(spec)
        captured = capsys.readouterr()
        assert "is not running" in captured.out

    def test_graceful_stop_clears_pid_file_and_invokes_callback(self, spec, capsys):
        spec.pid_file.write_text("12345")
        called: list[bool] = []
        # ``stop_daemon`` calls ``os.kill`` in this order:
        #   1. is_running -> kill(pid, 0) [must succeed]
        #   2. kill(pid, SIGTERM)         [must succeed]
        #   3. loop kill(pid, 0)          [raise ProcessLookupError -> exit]
        kill_calls: list[tuple[int, int]] = []

        def fake_kill(pid: int, sig: int) -> None:
            kill_calls.append((pid, sig))
            if len(kill_calls) >= 3:
                raise ProcessLookupError

        with (
            patch("os.kill", side_effect=fake_kill),
            patch("time.sleep"),
        ):
            daemon_module.stop_daemon(spec, on_stopped=lambda: called.append(True))

        assert called == [True]
        assert not spec.pid_file.exists()
        captured = capsys.readouterr()
        assert "stopped (was PID 12345)" in captured.out

    def test_force_kill_after_timeout_invokes_callback(self, spec, capsys):
        spec.pid_file.write_text("12345")
        called: list[bool] = []
        # Every os.kill returns 0 — no ProcessLookupError ever — so we
        # exhaust the wait loop and fall through to SIGKILL.
        with (
            patch("os.kill", return_value=None),
            patch("time.sleep"),
        ):
            daemon_module.stop_daemon(spec, on_stopped=lambda: called.append(True))

        assert called == [True]
        assert not spec.pid_file.exists()
        captured = capsys.readouterr()
        assert "force-killed" in captured.out


@pytest.mark.cli_unit
class TestDaemonSpec:
    def test_dataclass_is_frozen(self):
        spec = daemon_module.DaemonSpec(
            name="x",
            pid_file=Path("/tmp/x.pid"),
            log_file=Path("/tmp/x.log"),
        )
        with pytest.raises((AttributeError, Exception)):
            spec.name = "other"  # type: ignore[misc]
