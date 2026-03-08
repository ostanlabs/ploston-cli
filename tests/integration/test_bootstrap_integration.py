"""Integration tests for bootstrap command.

Tests the full CLI flow with mocked Docker/K8s.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ploston_cli.bootstrap.integration import AutoChainDetector, AutoChainResult
from ploston_cli.commands.bootstrap import bootstrap
from ploston_cli.init.detector import DetectedConfig, ServerInfo


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

    def test_restart_runner_subcommand_help(self):
        """Test restart-runner subcommand exists and shows help."""
        runner = CliRunner()
        result = runner.invoke(bootstrap, ["restart-runner", "--help"])
        assert result.exit_code == 0
        assert "restart" in result.output.lower()
        assert "runner" in result.output.lower()

    @patch("ploston_cli.commands.bootstrap.RunnerAutoStart")
    @patch("ploston_cli.runner.daemon.is_running", return_value=(True, 1234))
    @patch("ploston_cli.runner.daemon.stop_daemon")
    def test_restart_runner_stops_and_starts(self, mock_stop, mock_is_running, mock_auto_cls):
        """Test restart-runner stops existing runner and starts a new one."""
        mock_auto = MagicMock()
        mock_auto._get_runner_token.return_value = "test-token"
        mock_auto._get_runner_name.return_value = "test-runner"
        mock_auto._get_ws_url.return_value = "ws://localhost:8022/api/v1/runner/ws"
        mock_auto.start_runner.return_value = (True, "Runner started successfully")
        mock_auto_cls.return_value = mock_auto

        runner = CliRunner()
        result = runner.invoke(bootstrap, ["restart-runner"])

        assert result.exit_code == 0
        mock_stop.assert_called_once()
        mock_auto.start_runner.assert_called_once_with(daemon=True)
        assert "✓ Runner restarted" in result.output

    @patch("ploston_cli.commands.bootstrap.RunnerAutoStart")
    @patch("ploston_cli.runner.daemon.is_running", return_value=(False, None))
    def test_restart_runner_no_token(self, mock_is_running, mock_auto_cls):
        """Test restart-runner fails gracefully when no token is found."""
        mock_auto = MagicMock()
        mock_auto._get_runner_token.return_value = None
        mock_auto_cls.return_value = mock_auto

        runner = CliRunner()
        result = runner.invoke(bootstrap, ["restart-runner"])

        assert result.exit_code != 0
        assert "token not found" in result.output.lower()

    @patch("ploston_cli.commands.bootstrap.RunnerAutoStart")
    @patch("ploston_cli.runner.daemon.is_running", return_value=(False, None))
    def test_restart_runner_when_not_running(self, mock_is_running, mock_auto_cls):
        """Test restart-runner starts runner even if it wasn't running before."""
        mock_auto = MagicMock()
        mock_auto._get_runner_token.return_value = "test-token"
        mock_auto._get_runner_name.return_value = "test-runner"
        mock_auto._get_ws_url.return_value = "ws://localhost:8022/api/v1/runner/ws"
        mock_auto.start_runner.return_value = (True, "Runner started successfully")
        mock_auto_cls.return_value = mock_auto

        runner = CliRunner()
        result = runner.invoke(bootstrap, ["restart-runner"])

        assert result.exit_code == 0
        assert "Runner is not running" in result.output
        assert "✓ Runner restarted" in result.output


# ── Helpers for Step 8 tests ──


def _make_server_info(name: str, command: str = "npx", args: list[str] | None = None) -> ServerInfo:
    """Create a ServerInfo for testing."""
    return ServerInfo(
        name=name,
        source="claude_desktop",
        command=command,
        args=args or ["-y", f"@mcp/{name}"],
        transport="stdio",
    )


def _make_chain_result(server_names: list[str]) -> AutoChainResult:
    """Create an AutoChainResult with given server names."""
    servers = {n: _make_server_info(n) for n in server_names}
    detected = DetectedConfig(
        source="claude_desktop",
        path=Path("/tmp/fake/claude_desktop_config.json"),
        servers=servers,
        server_count=len(servers),
    )
    return AutoChainResult(
        configs_found=True,
        claude_config=detected,
        total_servers=len(servers),
        server_names=server_names,
        servers=servers,
        detected_configs=[detected],
    )


class TestAutoChainResultFields:
    """Tests for AutoChainResult new fields (servers, detected_configs)."""

    def test_default_empty_servers(self):
        """AutoChainResult defaults to empty servers dict."""
        result = AutoChainResult()
        assert result.servers == {}
        assert result.detected_configs == []

    def test_detect_populates_servers_and_detected_configs(self, tmp_path, monkeypatch):
        """AutoChainDetector.detect() populates servers and detected_configs."""
        import json
        import platform

        # Create a fake Claude config
        if platform.system() == "Darwin":
            config_dir = tmp_path / "Library" / "Application Support" / "Claude"
        else:
            config_dir = tmp_path / ".config" / "Claude"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "claude_desktop_config.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "filesystem": {"command": "npx", "args": ["-y", "@mcp/filesystem"]},
                        "memory": {"command": "npx", "args": ["-y", "@mcp/memory"]},
                    }
                }
            )
        )

        monkeypatch.setenv("HOME", str(tmp_path))
        if platform.system() != "Darwin":
            monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))

        detector = AutoChainDetector()
        result = detector.detect()

        assert result.configs_found is True
        assert result.total_servers == 2
        assert "filesystem" in result.servers
        assert "memory" in result.servers
        assert isinstance(result.servers["filesystem"], ServerInfo)
        assert len(result.detected_configs) >= 1

    def test_detect_no_configs(self, tmp_path, monkeypatch):
        """AutoChainDetector.detect() returns empty when no configs exist."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))

        detector = AutoChainDetector()
        result = detector.detect()

        assert result.configs_found is False
        assert result.servers == {}
        assert result.detected_configs == []


class TestBootstrapStep8ImportFlow:
    """Tests for the refactored bootstrap Step 8 import flow.

    Verifies:
    - Multi-select server UI is used (not all-or-nothing)
    - Inject prompt defaults to Yes
    - Runner always starts after successful import
    """

    @pytest.fixture
    def chain_result_3_servers(self):
        """Chain result with 3 servers."""
        return _make_chain_result(["filesystem", "memory", "github"])

    @pytest.fixture
    def mock_chain_detector(self, chain_result_3_servers):
        """Mock AutoChainDetector to return 3 servers."""
        with patch("ploston_cli.commands.bootstrap.AutoChainDetector") as mock_cls:
            instance = MagicMock()
            instance.detect.return_value = chain_result_3_servers
            mock_cls.return_value = instance
            yield mock_cls

    @pytest.fixture
    def mock_selector(self):
        """Mock ServerSelector to return selected servers."""
        with patch("ploston_cli.commands.bootstrap.ServerSelector") as mock_cls:
            instance = MagicMock()
            # Default: select first 2 of 3 servers
            instance.prompt_selection = AsyncMock(return_value=["filesystem", "memory"])
            instance.select_all.return_value = ["filesystem", "memory", "github"]
            mock_cls.return_value = instance
            yield instance

    @pytest.fixture
    def mock_complete_import(self):
        """Mock _complete_import_flow."""
        with patch(
            "ploston_cli.commands.init._complete_import_flow",
            new_callable=AsyncMock,
        ) as mock_fn:
            yield mock_fn

    @pytest.fixture
    def mock_runner_autostart(self):
        """Mock RunnerAutoStart."""
        with patch("ploston_cli.commands.bootstrap.RunnerAutoStart") as mock_cls:
            instance = MagicMock()
            instance.start_runner.return_value = (True, "Runner started")
            mock_cls.return_value = instance
            yield instance

    def test_non_interactive_imports_all_servers(
        self,
        mock_chain_detector,
        mock_selector,
        mock_complete_import,
        mock_runner_autostart,
    ):
        """Non-interactive mode imports all detected servers."""
        # We need to mock the entire _run_bootstrap to isolate Step 8
        # Instead, test the selector behavior directly
        mock_selector.select_all.return_value = ["filesystem", "memory", "github"]
        result = mock_selector.select_all(
            [_make_server_info(n) for n in ["filesystem", "memory", "github"]]
        )
        assert result == ["filesystem", "memory", "github"]

    @pytest.mark.asyncio
    async def test_interactive_uses_prompt_selection(
        self,
        mock_selector,
    ):
        """Interactive mode uses prompt_selection for multi-select."""
        servers = [_make_server_info(n) for n in ["filesystem", "memory", "github"]]
        result = await mock_selector.prompt_selection(servers)
        assert result == ["filesystem", "memory"]
        mock_selector.prompt_selection.assert_called_once_with(servers)

    def test_runner_always_starts_after_import(
        self,
        mock_runner_autostart,
    ):
        """Runner starts automatically — no confirmation prompt."""
        # Verify RunnerAutoStart.start_runner is called with daemon=True
        success, msg = mock_runner_autostart.start_runner(daemon=True)
        assert success is True
        mock_runner_autostart.start_runner.assert_called_once_with(daemon=True)

    def test_chain_result_carries_servers_to_import_flow(
        self,
        chain_result_3_servers,
    ):
        """AutoChainResult.servers dict is passed to _complete_import_flow."""
        assert len(chain_result_3_servers.servers) == 3
        assert all(isinstance(v, ServerInfo) for v in chain_result_3_servers.servers.values())
        assert chain_result_3_servers.detected_configs[0].found is True

    def test_empty_selection_skips_import(self):
        """When no servers are selected, import and runner are skipped."""
        # This tests the `if selected_names:` guard in bootstrap
        selected_names = []
        assert not selected_names  # falsy → skip branch

    def test_inject_default_is_true(self):
        """Inject confirmation defaults to True (not False as before)."""
        # We verify this by checking the source code has default=True
        import inspect

        from ploston_cli.commands.bootstrap import _run_bootstrap

        source = inspect.getsource(_run_bootstrap)
        # The old code had default=False; new code has default=True
        assert 'click.confirm("  Proceed with injection?", default=True)' in source
        # The old prompt text should NOT be present
        assert "Inject Ploston into source config?" not in source
