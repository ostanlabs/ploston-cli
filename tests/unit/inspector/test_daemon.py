"""Unit tests for the inspector daemon wrapper.

Verifies that the inspector wrapper delegates to the shared daemon scaffolding
with the correct ``DaemonSpec`` and that the readiness probe behaves as
expected without making real network calls.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from ploston_cli.inspector import daemon as inspector_daemon
from ploston_cli.shared import daemon as shared_daemon


@pytest.mark.cli_unit
class TestHealthProbe:
    def test_probe_returns_true_on_2xx(self):
        probe = inspector_daemon._make_health_probe("127.0.0.1", 7777)
        fake_resp = MagicMock(status=200)
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)
        with patch("ploston_cli.inspector.daemon.urlopen", return_value=fake_resp):
            assert probe() is True

    def test_probe_returns_false_on_non_2xx(self):
        probe = inspector_daemon._make_health_probe("127.0.0.1", 7777)
        fake_resp = MagicMock(status=500)
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)
        with patch("ploston_cli.inspector.daemon.urlopen", return_value=fake_resp):
            assert probe() is False

    def test_probe_returns_false_on_connection_error(self):
        probe = inspector_daemon._make_health_probe("127.0.0.1", 7777)
        with patch(
            "ploston_cli.inspector.daemon.urlopen", side_effect=URLError("connection refused")
        ):
            assert probe() is False

    def test_probe_returns_false_on_os_error(self):
        probe = inspector_daemon._make_health_probe("127.0.0.1", 7777)
        with patch("ploston_cli.inspector.daemon.urlopen", side_effect=OSError):
            assert probe() is False


@pytest.mark.cli_unit
class TestIsRunningDelegation:
    def test_is_running_uses_inspector_pid_file(self, tmp_path: Path):
        fake_pid_file = tmp_path / "inspector.pid"
        fake_log_file = tmp_path / "inspector.log"
        with (
            patch.object(inspector_daemon, "INSPECTOR_PID_FILE", fake_pid_file),
            patch.object(inspector_daemon, "INSPECTOR_LOG_FILE", fake_log_file),
            patch.object(
                inspector_daemon,
                "_DEFAULT_SPEC",
                shared_daemon.DaemonSpec(
                    name="inspector",
                    pid_file=fake_pid_file,
                    log_file=fake_log_file,
                ),
            ),
        ):
            # No PID file -> not running.
            assert inspector_daemon.is_running() == (False, None)
            assert inspector_daemon.get_pid() is None

    def test_is_running_when_pid_file_exists(self, tmp_path: Path):
        fake_pid_file = tmp_path / "inspector.pid"
        fake_log_file = tmp_path / "inspector.log"
        fake_pid_file.write_text("12345")

        spec = shared_daemon.DaemonSpec(
            name="inspector",
            pid_file=fake_pid_file,
            log_file=fake_log_file,
        )
        with (
            patch.object(inspector_daemon, "_DEFAULT_SPEC", spec),
            patch("os.kill", return_value=None),
        ):
            assert inspector_daemon.is_running() == (True, 12345)
            assert inspector_daemon.get_pid() == 12345


@pytest.mark.cli_unit
class TestStopDaemonDelegation:
    def test_stop_daemon_calls_shared_with_callback(self, tmp_path: Path):
        spec = shared_daemon.DaemonSpec(
            name="inspector",
            pid_file=tmp_path / "i.pid",
            log_file=tmp_path / "i.log",
        )
        called: list[bool] = []
        with (
            patch.object(inspector_daemon, "_DEFAULT_SPEC", spec),
            patch.object(shared_daemon, "stop_daemon") as mock_stop,
        ):
            inspector_daemon.stop_daemon(on_stopped=lambda: called.append(True))
        mock_stop.assert_called_once()
        # First positional arg is the spec, kwarg is ``on_stopped``.
        args, kwargs = mock_stop.call_args
        assert args[0] is spec
        assert "on_stopped" in kwargs


@pytest.mark.cli_unit
class TestStartDaemonDelegation:
    def test_start_builds_spec_with_health_probe(self, tmp_path: Path):
        captured: dict = {}

        def fake_start(spec, run_func, **kwargs):
            captured["spec"] = spec
            captured["run_func"] = run_func
            captured["kwargs"] = kwargs

        with (
            patch.object(inspector_daemon, "INSPECTOR_PID_FILE", tmp_path / "inspector.pid"),
            patch.object(inspector_daemon, "INSPECTOR_LOG_FILE", tmp_path / "inspector.log"),
            patch.object(shared_daemon, "start_daemon", side_effect=fake_start),
        ):
            inspector_daemon.start_daemon(
                lambda **_: None,
                host="127.0.0.1",
                port=7777,
                url="http://localhost:8022",
                token=None,
            )

        spec = captured["spec"]
        assert spec.name == "inspector"
        assert spec.pid_file.name == "inspector.pid"
        assert spec.log_file.name == "inspector.log"
        assert spec.health_probe is not None
        # ``host``/``port`` parameterise the spec's health probe *and* must
        # be forwarded to the daemon-side ``run_func`` so it binds the same
        # address. All other kwargs pass straight through.
        assert captured["kwargs"]["host"] == "127.0.0.1"
        assert captured["kwargs"]["port"] == 7777
        assert captured["kwargs"]["url"] == "http://localhost:8022"
        assert captured["kwargs"]["token"] is None
