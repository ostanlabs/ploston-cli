"""Phase-3 robustness tests for daemon PID-file safety.

Covers two hazards:

1. PID recycling — ``is_running`` must not report a recycled PID belonging to
   an unrelated process as the daemon. When a spec declares an
   ``identity_token``, the process cmdline is verified before trusting the PID.

2. Double-start race — ``start_daemon`` acquires an exclusive lock around the
   is_running check + PID write so two concurrent starts cannot both spawn.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ploston_cli.shared import daemon as daemon_module


@pytest.fixture
def identified_spec(tmp_path: Path) -> daemon_module.DaemonSpec:
    return daemon_module.DaemonSpec(
        name="testd",
        pid_file=tmp_path / "test.pid",
        log_file=tmp_path / "test.log",
        identity_token="ploston-testd",
    )


@pytest.mark.cli_unit
class TestPidIdentity:
    def test_is_running_false_for_unrelated_process(self, identified_spec):
        """A live PID whose cmdline is not a ploston daemon → not running."""
        identified_spec.pid_file.write_text("12345")
        # os.kill(pid, 0) succeeds (process alive) but it is some unrelated
        # process — its cmdline does not match the daemon identity token.
        with (
            patch("os.kill", return_value=None),
            patch(
                "ploston_cli.shared.daemon._read_process_cmdline",
                return_value="/usr/bin/some-unrelated-program --flag",
            ),
        ):
            alive, pid = daemon_module.is_running(identified_spec)
        assert alive is False
        assert pid is None

    def test_is_running_true_for_matching_process(self, identified_spec):
        """A live PID whose cmdline matches the daemon identity → running."""
        identified_spec.pid_file.write_text("12345")
        with (
            patch("os.kill", return_value=None),
            patch(
                "ploston_cli.shared.daemon._read_process_cmdline",
                return_value="python -m ploston-testd run",
            ),
        ):
            alive, pid = daemon_module.is_running(identified_spec)
        assert alive is True
        assert pid == 12345

    def test_is_running_degrades_when_cmdline_unavailable(self, identified_spec):
        """If the cmdline can't be read at all, fall back to the kill check."""
        identified_spec.pid_file.write_text("12345")
        with (
            patch("os.kill", return_value=None),
            patch(
                "ploston_cli.shared.daemon._read_process_cmdline",
                return_value=None,
            ),
        ):
            alive, pid = daemon_module.is_running(identified_spec)
        assert alive is True
        assert pid == 12345


@pytest.mark.cli_unit
class TestDoubleStartLock:
    def test_second_start_while_locked_is_rejected(self, tmp_path):
        """When the start lock is already held, a concurrent start exits 1."""
        spec = daemon_module.DaemonSpec(
            name="testd",
            pid_file=tmp_path / "test.pid",
            log_file=tmp_path / "test.log",
        )

        # Hold the lock for the duration of the second start attempt.
        with daemon_module._start_lock(spec):
            with patch("os.fork") as mock_fork:
                with pytest.raises(SystemExit) as exc:
                    daemon_module.start_daemon(spec, run_func=lambda: None)
                # Must not have forked — rejected before spawning.
                mock_fork.assert_not_called()
        assert exc.value.code == 1
