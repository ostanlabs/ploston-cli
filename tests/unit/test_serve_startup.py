"""Unit tests for ael serve startup behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ploston_cli.main import cli


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


class TestServeStartup:
    """Tests for ael serve startup behavior."""

    def test_serve_auto_detect_running_mode(self, runner):
        """Test auto-detect running mode when config exists."""
        with patch("ploston_core.config.ConfigLoader") as mock_loader_class, \
             patch("ploston_cli.application.AELApplication") as mock_app_class:
            mock_loader = MagicMock()
            mock_config = MagicMock()
            mock_loader.load.return_value = mock_config
            mock_loader._config_path = "/path/to/config.yaml"
            mock_loader_class.return_value = mock_loader

            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.mcp_frontend = MagicMock()
            mock_app.mcp_frontend.start = AsyncMock(side_effect=KeyboardInterrupt)
            mock_app.mcp_manager = MagicMock()
            mock_app.mcp_manager._clients = {"server1": MagicMock()}
            mock_app.workflow_registry = MagicMock()
            mock_app.workflow_registry.list_workflows.return_value = []
            mock_app_class.return_value = mock_app

            result = runner.invoke(cli, ["serve"])

            # Check stderr output
            assert "[AEL] Config loaded from:" in result.output
            assert "[AEL] Mode: running" in result.output

    def test_serve_auto_detect_config_mode(self, runner):
        """Test auto-detect configuration mode when no config exists."""
        from ploston_core.errors import AELError

        with patch("ploston_core.config.ConfigLoader") as mock_loader_class:
            mock_loader = MagicMock()
            mock_loader.load.side_effect = AELError(
                code="CONFIG_NOT_FOUND",
                message="Config not found",
                category="config",
            )
            mock_loader_class.return_value = mock_loader

            with patch("ploston_core.config.StagedConfig"):
                with patch("ploston_core.config.tools.ConfigToolRegistry"):
                    with patch("ploston_core.mcp_frontend.MCPFrontend") as mock_frontend_class:
                        mock_frontend = MagicMock()
                        mock_frontend.start = AsyncMock(side_effect=KeyboardInterrupt)
                        mock_frontend_class.return_value = mock_frontend

                        result = runner.invoke(cli, ["serve"])

                        # Check stderr output
                        assert "[AEL] No config found" in result.output
                        assert "[AEL] Mode: configuration" in result.output
                        assert "[AEL] Use config tools" in result.output

    def test_serve_forced_config_mode(self, runner):
        """Test forced configuration mode via --mode flag."""
        with patch("ploston_core.config.ConfigLoader") as mock_loader_class:
            mock_loader = MagicMock()
            mock_loader_class.return_value = mock_loader

            with patch("ploston_core.config.StagedConfig"):
                with patch("ploston_core.config.tools.ConfigToolRegistry"):
                    with patch("ploston_core.mcp_frontend.MCPFrontend") as mock_frontend_class:
                        mock_frontend = MagicMock()
                        mock_frontend.start = AsyncMock(side_effect=KeyboardInterrupt)
                        mock_frontend_class.return_value = mock_frontend

                        result = runner.invoke(cli, ["serve", "--mode=configuration"])

                        # Check stderr output
                        assert "[AEL] Mode: configuration (forced via --mode flag)" in result.output

    def test_serve_forced_running_mode_no_config(self, runner):
        """Test forced running mode fails when no config exists."""
        from ploston_core.errors import AELError

        with patch("ploston_core.config.ConfigLoader") as mock_loader_class:
            mock_loader = MagicMock()
            mock_loader.load.side_effect = AELError(
                code="CONFIG_NOT_FOUND",
                message="Config not found",
                category="config",
            )
            mock_loader_class.return_value = mock_loader

            result = runner.invoke(cli, ["serve", "--mode=running"])

            assert result.exit_code == 1
            assert "[AEL] Error:" in result.output
            assert "Cannot start in running mode" in result.output

    def test_serve_forced_running_mode_with_config(self, runner):
        """Test forced running mode succeeds when config exists."""
        with patch("ploston_core.config.ConfigLoader") as mock_loader_class:
            mock_loader = MagicMock()
            mock_config = MagicMock()
            mock_loader.load.return_value = mock_config
            mock_loader._config_path = "/path/to/config.yaml"
            mock_loader_class.return_value = mock_loader

            with patch("ploston_cli.application.AELApplication") as mock_app_class:
                mock_app = MagicMock()
                mock_app.initialize = AsyncMock()
                mock_app.shutdown = AsyncMock()
                mock_app.mcp_frontend = MagicMock()
                mock_app.mcp_frontend.start = AsyncMock(side_effect=KeyboardInterrupt)
                mock_app.mcp_manager = MagicMock()
                mock_app.mcp_manager._clients = {}
                mock_app.workflow_registry = MagicMock()
                mock_app.workflow_registry.list_workflows.return_value = []
                mock_app_class.return_value = mock_app

                result = runner.invoke(cli, ["serve", "--mode=running"])

                assert "[AEL] Mode: running (forced via --mode flag)" in result.output
