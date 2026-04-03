"""Tests for ploston server command group (T-768).

See: DEC169-175_ROUTING_TAGS_CLI_SPEC.md §6
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ploston_cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestServerList:
    """Tests for ploston server list."""

    def test_server_list_output_format(self, runner):
        """ploston server list → table with name, source, tool count."""
        mock_tools = [
            {"name": "read_file", "server": "filesystem", "source": "runner"},
            {"name": "write_file", "server": "filesystem", "source": "runner"},
            {"name": "search_issues", "server": "github", "source": "runner"},
        ]

        async def mock_list_tools(**kwargs):
            return mock_tools

        with patch("ploston_cli.commands.server.PlostClient") as mock_client:
            instance = AsyncMock()
            instance.list_tools = mock_list_tools
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = runner.invoke(cli, ["-s", "http://localhost:8022", "server", "list"])
            assert result.exit_code == 0
            assert "filesystem" in result.output
            assert "github" in result.output

    def test_server_list_json(self, runner):
        """ploston server list --json outputs JSON."""

        async def mock_list_tools(**kwargs):
            return [{"name": "t1", "server": "fs", "source": "runner"}]

        with patch("ploston_cli.commands.server.PlostClient") as mock_client:
            instance = AsyncMock()
            instance.list_tools = mock_list_tools
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = runner.invoke(cli, ["-s", "http://localhost:8022", "--json", "server", "list"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert isinstance(data, list)
            assert data[0]["name"] == "fs"


class TestServerAdd:
    """Tests for ploston server add."""

    def test_server_add_manual_mode(self, runner):
        """ploston server add fetch --command npx --args '["@mcp/fetch"]'."""
        with patch("ploston_cli.commands.server.PlostClient") as mock_client:
            instance = AsyncMock()
            instance.get_runner_token = AsyncMock(return_value="tok")
            instance.push_runner_config = AsyncMock(return_value={})
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = runner.invoke(
                cli,
                [
                    "-s",
                    "http://localhost:8022",
                    "server",
                    "add",
                    "fetch",
                    "--command",
                    "npx",
                    "--args",
                    '["@mcp/fetch"]',
                ],
            )
            assert result.exit_code == 0
            assert "fetch" in result.output
            # Verify merge=True was passed
            call_kwargs = instance.push_runner_config.call_args
            assert call_kwargs[1]["merge"] is True
            assert "fetch" in call_kwargs[1]["mcp_servers"]

    def test_server_add_requires_name_or_detect(self, runner):
        """ploston server add without name or --detect errors."""
        result = runner.invoke(cli, ["-s", "http://localhost:8022", "server", "add"])
        assert result.exit_code != 0


class TestServerRemove:
    """Tests for ploston server remove."""

    def test_server_remove_unregisters(self, runner):
        """ploston server remove github → calls push_runner_config without that server."""
        existing_config = {
            "mcp_servers": {"github": {"command": "npx"}, "fs": {"command": "node"}},
            "token": "tok",
        }

        with patch("ploston_cli.commands.server.PlostClient") as mock_client:
            instance = AsyncMock()
            instance._request = AsyncMock(return_value=existing_config)
            instance.push_runner_config = AsyncMock(return_value={})
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = runner.invoke(
                cli,
                ["-s", "http://localhost:8022", "server", "remove", "github", "-f"],
            )
            assert result.exit_code == 0
            assert "github" in result.output
            # Verify push was called with only 'fs' (github removed)
            call_kwargs = instance.push_runner_config.call_args
            assert "github" not in call_kwargs[1]["mcp_servers"]
            assert "fs" in call_kwargs[1]["mcp_servers"]
