"""Unit tests for bridge --expose and --runner CLI flag parsing.

Tests for --expose/--tools mutual exclusivity, --runner flag handling,
and BridgeServer parameter wiring.
"""

from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

from ploston_cli.bridge.proxy import BridgeProxy
from ploston_cli.bridge.server import BridgeServer
from ploston_cli.commands.bridge import bridge_command

pytestmark = [pytest.mark.bridge, pytest.mark.bridge_unit]


# =============================================================================
# --expose / --tools mutual exclusivity tests
# =============================================================================


class TestExposeToolsMutualExclusivity:
    """Tests for --expose and --tools mutual exclusivity."""

    def test_expose_and_tools_raises_error(self):
        """Click raises UsageError when both --expose and --tools (non-default) provided."""
        runner = CliRunner()
        result = runner.invoke(
            bridge_command,
            ["--url", "http://localhost:8022", "--expose", "filesystem", "--tools", "local"],
        )
        assert result.exit_code != 0
        assert (
            "mutually exclusive" in result.output.lower()
            or "mutually exclusive" in str(result.exception).lower()
        )

    def test_expose_alone_accepted(self):
        """--expose alone is accepted (tools defaults to 'all')."""
        runner = CliRunner()
        # This will fail to connect but should not raise a UsageError
        result = runner.invoke(
            bridge_command,
            ["--url", "http://localhost:8022", "--expose", "filesystem"],
        )
        # Should not be a usage error — it will fail on connection, which is expected
        if result.exit_code != 0:
            assert "mutually exclusive" not in (result.output or "").lower()

    def test_tools_alone_accepted(self):
        """--tools alone is accepted."""
        runner = CliRunner()
        result = runner.invoke(
            bridge_command,
            ["--url", "http://localhost:8022", "--tools", "local"],
        )
        # Should not be a usage error
        if result.exit_code != 0:
            assert "mutually exclusive" not in (result.output or "").lower()


# =============================================================================
# --runner flag parsing tests
# =============================================================================


class TestRunnerFlagParsing:
    """Tests for --runner flag parsing and BridgeServer wiring."""

    def test_runner_stored_on_bridge_server(self):
        """--runner value is stored on BridgeServer instance."""
        mock_proxy = AsyncMock(spec=BridgeProxy)
        server = BridgeServer(proxy=mock_proxy, expose="filesystem", runner="mac")
        assert server.runner == "mac"

    def test_runner_none_when_not_provided(self):
        """runner is None when --runner not provided."""
        mock_proxy = AsyncMock(spec=BridgeProxy)
        server = BridgeServer(proxy=mock_proxy, expose="filesystem")
        assert server.runner is None

    def test_expose_stored_on_bridge_server(self):
        """--expose value is stored on BridgeServer instance."""
        mock_proxy = AsyncMock(spec=BridgeProxy)
        server = BridgeServer(proxy=mock_proxy, expose="github")
        assert server.expose == "github"

    def test_expose_none_by_default(self):
        """expose is None by default."""
        mock_proxy = AsyncMock(spec=BridgeProxy)
        server = BridgeServer(proxy=mock_proxy)
        assert server.expose is None

    @pytest.mark.asyncio
    async def test_ambiguity_error_surfaced_on_tools_list(self):
        """ExposeAmbiguityError is surfaced as JSON-RPC error on tools/list."""
        mock_proxy = AsyncMock(spec=BridgeProxy)
        mock_proxy.send_request.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "mac__filesystem__read_file", "description": "...", "inputSchema": {}},
                    {
                        "name": "build__filesystem__read_file",
                        "description": "...",
                        "inputSchema": {},
                    },
                ]
            },
        }
        server = BridgeServer(proxy=mock_proxy, expose="filesystem")

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = await server.handle_request(request)

        assert "error" in response
        assert (
            "multiple runners" in response["error"]["message"].lower()
            or "disambiguate" in response["error"]["message"].lower()
        )

    def test_runner_flag_accepted_by_cli(self):
        """--runner flag is accepted by the CLI."""
        runner = CliRunner()
        result = runner.invoke(
            bridge_command,
            ["--url", "http://localhost:8022", "--expose", "filesystem", "--runner", "mac"],
        )
        # Should not be a usage error
        if result.exit_code != 0:
            assert "no such option" not in (result.output or "").lower()
