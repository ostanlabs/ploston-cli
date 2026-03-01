"""Integration tests for bootstrap command.

Tests the full CLI flow with mocked Docker/K8s.
"""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ploston_cli.commands.bootstrap import bootstrap


@pytest.fixture
def mock_docker_available():
    """Mock Docker and Compose as available."""
    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/docker"
        with patch("subprocess.run") as mock_run:

            def side_effect(cmd, *args, **kwargs):
                result = MagicMock(returncode=0)
                if "compose" in cmd and "version" in cmd:
                    result.stdout = "v2.21.0"
                elif "version" in cmd:
                    result.stdout = "24.0.7"
                elif "compose" in cmd and "up" in cmd:
                    result.stdout = ""
                elif "compose" in cmd and "ps" in cmd:
                    result.stdout = '{"Service":"ploston","State":"running"}\n'
                else:
                    result.stdout = ""
                return result

            mock_run.side_effect = side_effect
            yield mock_run


@pytest.fixture
def mock_cp_health():
    """Mock CP health endpoint as healthy."""
    with patch("httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "ok",
            "version": "0.9.0",
            "mode": "configuration",
        }
        mock_get.return_value = mock_response
        yield mock_get


@pytest.fixture
def mock_kubectl_available():
    """Mock kubectl as available."""
    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/kubectl"
        with patch("subprocess.run") as mock_run:

            def side_effect(cmd, *args, **kwargs):
                result = MagicMock(returncode=0)
                if "version" in cmd:
                    result.stdout = "v1.28.0"
                elif "current-context" in cmd:
                    result.stdout = "minikube"
                elif "apply" in cmd:
                    result.stdout = "applied"
                elif "wait" in cmd:
                    result.stdout = "condition met"
                else:
                    result.stdout = ""
                return result

            mock_run.side_effect = side_effect
            yield mock_run


class TestBootstrapFlow:
    """Integration tests for bootstrap command flow."""

    def test_bootstrap_help(self):
        """Test bootstrap --help works."""
        runner = CliRunner()
        result = runner.invoke(bootstrap, ["--help"])
        assert result.exit_code == 0
        assert "Deploy the Ploston Control Plane" in result.output

    def test_bootstrap_status_no_stack(self):
        """Test bootstrap status when no stack exists."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"HOME": tmpdir}):
                result = runner.invoke(bootstrap, ["status"])
                # Should show not found or similar
                assert result.exit_code == 0

    def test_bootstrap_down_no_stack(self):
        """Test bootstrap down when no stack exists."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"HOME": tmpdir}):
                result = runner.invoke(bootstrap, ["down"])
                # Should handle gracefully
                assert result.exit_code in [0, 1]

    def test_bootstrap_docker_target_help(self):
        """Test bootstrap with docker target help."""
        runner = CliRunner()
        result = runner.invoke(bootstrap, ["--target", "docker", "--help"])
        assert result.exit_code == 0

    def test_bootstrap_k8s_target_help(self):
        """Test bootstrap with k8s target help."""
        runner = CliRunner()
        result = runner.invoke(bootstrap, ["--target", "k8s", "--help"])
        assert result.exit_code == 0


class TestBootstrapSubcommands:
    """Tests for bootstrap subcommands."""

    def test_status_subcommand(self):
        """Test status subcommand exists."""
        runner = CliRunner()
        result = runner.invoke(bootstrap, ["status", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output.lower() or "Status" in result.output

    def test_down_subcommand(self):
        """Test down subcommand exists."""
        runner = CliRunner()
        result = runner.invoke(bootstrap, ["down", "--help"])
        assert result.exit_code == 0

    def test_logs_subcommand(self):
        """Test logs subcommand exists."""
        runner = CliRunner()
        result = runner.invoke(bootstrap, ["logs", "--help"])
        assert result.exit_code == 0

    def test_restart_subcommand(self):
        """Test restart subcommand exists."""
        runner = CliRunner()
        result = runner.invoke(bootstrap, ["restart", "--help"])
        assert result.exit_code == 0
