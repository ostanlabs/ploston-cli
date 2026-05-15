"""Unit tests for RunnerAutoStart.check_runner_status."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from ploston_cli.bootstrap.integration import RunnerAutoStart

SUBPROCESS_RUN = "ploston_cli.bootstrap.integration.subprocess.run"


@pytest.fixture
def auto_start():
    return RunnerAutoStart("http://localhost:8022")


class TestCheckRunnerStatus:
    """Tests for RunnerAutoStart.check_runner_status."""

    def test_running_when_process_alive(self, auto_start):
        """Returns (True, ...) when runner reports running with PID."""
        mock_result = subprocess.CompletedProcess(
            args=["ploston", "runner", "status"],
            returncode=0,
            stdout="Runner: running (PID 12345)\n  Name: local\n",
            stderr="",
        )
        with patch(SUBPROCESS_RUN, return_value=mock_result):
            running, msg = auto_start.check_runner_status()

        assert running is True
        assert "running" in msg.lower()

    def test_not_running_exit_code_1(self, auto_start):
        """Returns (False, ...) when runner exits with code 1."""
        mock_result = subprocess.CompletedProcess(
            args=["ploston", "runner", "status"],
            returncode=1,
            stdout="Runner: not running\n",
            stderr="",
        )
        with patch(SUBPROCESS_RUN, return_value=mock_result):
            running, msg = auto_start.check_runner_status()

        assert running is False

    def test_not_running_old_cli_exit_code_0(self, auto_start):
        """Returns (False, ...) when old CLI exits 0 but output says 'not running'.

        Defense-in-depth: older CLI versions always exit 0 even when
        the runner is not running.
        """
        mock_result = subprocess.CompletedProcess(
            args=["ploston", "runner", "status"],
            returncode=0,
            stdout="Runner: not running\n",
            stderr="",
        )
        with patch(SUBPROCESS_RUN, return_value=mock_result):
            running, msg = auto_start.check_runner_status()

        assert running is False

    def test_cli_not_found(self, auto_start):
        """Returns (False, ...) when ploston CLI is not installed."""
        with patch(SUBPROCESS_RUN, side_effect=FileNotFoundError):
            running, msg = auto_start.check_runner_status()

        assert running is False
        assert "not found" in msg.lower()

    def test_unexpected_error(self, auto_start):
        """Returns (False, ...) on unexpected errors."""
        with patch(SUBPROCESS_RUN, side_effect=OSError("permission denied")):
            running, msg = auto_start.check_runner_status()

        assert running is False
        assert "permission denied" in msg.lower()
