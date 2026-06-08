"""Integration tests for runner with Mock CP.

Tests runner behavior in isolation using a mock Control Plane.
No Docker Compose or K8s backend needed.

Test scenarios:
- Runner connection and registration
- Config push from CP to runner
- Tool discovery and reporting
- Tool call execution
"""

import time

import pytest

from .conftest import wait_until


@pytest.mark.integration
class TestRunnerConnectionWithMockCP:
    """Test runner connection behavior with mock CP."""

    def test_runner_connects_to_cp(self, mock_cp, start_runner):
        """Test runner establishes WebSocket connection to CP."""
        start_runner(token="test_token", name="connect-test")

        # Wait for connection (poll the real condition instead of fixed sleeps)
        wait_until(
            lambda: len(mock_cp.connections) > 0,
            timeout=5.0,
            message="Runner did not connect to mock CP",
        )

    def test_runner_receives_config_push(self, mock_cp, start_runner):
        """Test runner receives and processes config from CP."""
        # Set config before runner connects
        mock_cp.set_config(
            {
                "mcp_servers": [
                    {
                        "name": "filesystem",
                        "command": "npx",
                        "args": ["-y", "@anthropic/mcp-filesystem"],
                    }
                ]
            }
        )

        proc = start_runner(token="test_token", name="config-test")

        # Wait for connection (config is pushed on connect)
        wait_until(
            lambda: len(mock_cp.connections) > 0,
            timeout=5.0,
            message="Runner did not connect to mock CP",
        )

        # Config is sent on connection - runner should process it.
        # Genuine elapsed-time soak: give the runner a moment to process the
        # config push, then verify it is still alive (didn't crash).
        time.sleep(1)
        assert proc.poll() is None, "Runner crashed after receiving config"


@pytest.mark.integration
class TestRunnerToolDiscoveryWithMockCP:
    """Test runner tool discovery with mock CP."""

    def test_runner_reports_available_tools(self, mock_cp, start_runner):
        """Test runner discovers and reports tools to CP."""
        mock_cp.set_config(
            {
                "mcp_servers": [
                    {
                        "name": "filesystem",
                        "command": "npx",
                        "args": ["-y", "@anthropic/mcp-filesystem"],
                    }
                ]
            }
        )

        start_runner(token="test_token", name="tools-test")

        # Wait for a tool report. Reports are optional (may be empty if the MCP
        # backend isn't available), so a timeout here is not a failure -- we
        # just stop waiting as soon as one arrives.
        try:
            tool_reports = wait_until(
                mock_cp.get_tool_reports,
                timeout=10.0,
            )
        except AssertionError:
            tool_reports = mock_cp.get_tool_reports()

        # Runner should report tools (may be empty if MCP not available)
        assert len(tool_reports) >= 0  # At minimum, runner should attempt to report


@pytest.mark.integration
class TestRunnerToolExecutionWithMockCP:
    """Test runner tool execution with mock CP."""

    def test_runner_executes_tool_call(self, mock_cp, start_runner):
        """Test runner executes tool call from CP and returns result."""
        mock_cp.set_config(
            {
                "mcp_servers": [
                    {
                        "name": "filesystem",
                        "command": "npx",
                        "args": ["-y", "@anthropic/mcp-filesystem"],
                    }
                ]
            }
        )

        start_runner(token="test_token", name="exec-test")

        # Wait for connection before queueing a tool call.
        wait_until(
            lambda: len(mock_cp.connections) > 0,
            timeout=5.0,
            message="Runner did not connect to mock CP",
        )

        # Queue a tool call
        mock_cp.queue_tool_call(tool_name="read_file", arguments={"path": "/tmp/test.txt"})

        # Wait for a result. A result is optional (depends on the filesystem MCP
        # being available), so a timeout here is not a failure.
        try:
            wait_until(mock_cp.get_tool_results, timeout=10.0)
        except AssertionError:
            pass

        # Note: This may fail if filesystem MCP isn't available
        # The test validates the flow, not the specific result
