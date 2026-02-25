"""Unit tests for ploston_cli.runner.types module."""

from datetime import UTC, datetime

import pytest

from ploston_cli.runner.types import (
    JSONRPCErrorCode,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    MCPAvailability,
    MCPConfig,
    MCPStatus,
    RunnerConfig,
    RunnerConnectionStatus,
    RunnerMCPConfig,
    RunnerMethods,
    RunnerStatus,
)


@pytest.mark.runner_unit
class TestRunnerConfig:
    """Tests for RunnerConfig dataclass."""

    def test_create_with_required_fields(self):
        """Test creating config with required fields only."""
        config = RunnerConfig(
            control_plane_url="wss://cp.example.com/runner",
            auth_token="test-token",
            runner_name="test-runner",
        )

        assert config.control_plane_url == "wss://cp.example.com/runner"
        assert config.auth_token == "test-token"
        assert config.runner_name == "test-runner"
        # Check defaults
        assert config.reconnect_delay == 5.0
        assert config.max_reconnect_delay == 60.0
        assert config.heartbeat_interval == 30.0
        assert config.health_check_interval == 30.0

    def test_create_with_all_fields(self):
        """Test creating config with all fields."""
        config = RunnerConfig(
            control_plane_url="wss://cp.example.com/runner",
            auth_token="test-token",
            runner_name="test-runner",
            reconnect_delay=10.0,
            max_reconnect_delay=120.0,
            heartbeat_interval=15.0,
            health_check_interval=45.0,
        )

        assert config.reconnect_delay == 10.0
        assert config.max_reconnect_delay == 120.0
        assert config.heartbeat_interval == 15.0
        assert config.health_check_interval == 45.0


@pytest.mark.runner_unit
class TestMCPAvailability:
    """Tests for MCPAvailability dataclass."""

    def test_create_available_mcp(self):
        """Test creating an available MCP status."""
        now = datetime.now(UTC)
        avail = MCPAvailability(
            name="filesystem",
            status=MCPStatus.AVAILABLE,
            tools=["fs_read", "fs_write", "fs_list"],
            last_checked=now,
        )

        assert avail.name == "filesystem"
        assert avail.status == MCPStatus.AVAILABLE
        assert len(avail.tools) == 3
        assert avail.error is None
        assert avail.last_checked == now

    def test_create_unavailable_mcp(self):
        """Test creating an unavailable MCP status."""
        avail = MCPAvailability(
            name="docker",
            status=MCPStatus.UNAVAILABLE,
            error="Docker daemon not running",
        )

        assert avail.name == "docker"
        assert avail.status == MCPStatus.UNAVAILABLE
        assert avail.tools == []
        assert avail.error == "Docker daemon not running"


@pytest.mark.runner_unit
class TestRunnerStatus:
    """Tests for RunnerStatus dataclass."""

    def test_create_status(self):
        """Test creating runner status."""
        status = RunnerStatus(
            name="my-runner",
            connection_status=RunnerConnectionStatus.CONNECTED,
            uptime_seconds=3600.0,
        )

        assert status.name == "my-runner"
        assert status.connection_status == RunnerConnectionStatus.CONNECTED
        assert status.uptime_seconds == 3600.0
        assert status.available_mcps == []
        assert status.unavailable_mcps == []


@pytest.mark.runner_unit
class TestJSONRPCMessages:
    """Tests for JSON-RPC message types."""

    def test_jsonrpc_request(self):
        """Test JSONRPCRequest model."""
        request = JSONRPCRequest(
            id=1,
            method="runner/register",
            params={"token": "test", "name": "runner1"},
        )

        assert request.jsonrpc == "2.0"
        assert request.id == 1
        assert request.method == "runner/register"
        assert request.params == {"token": "test", "name": "runner1"}

        # Test serialization
        json_str = request.model_dump_json()
        assert '"jsonrpc":"2.0"' in json_str
        assert '"method":"runner/register"' in json_str

    def test_jsonrpc_response_success(self):
        """Test JSONRPCResponse with result."""
        response = JSONRPCResponse(
            id=1,
            result={"status": "ok"},
        )

        assert response.jsonrpc == "2.0"
        assert response.id == 1
        assert response.result == {"status": "ok"}
        assert response.error is None

    def test_jsonrpc_response_error(self):
        """Test JSONRPCResponse with error."""
        response = JSONRPCResponse(
            id=1,
            error={
                "code": JSONRPCErrorCode.AUTH_FAILED,
                "message": "Invalid token",
            },
        )

        assert response.id == 1
        assert response.result is None
        assert response.error["code"] == -32000
        assert response.error["message"] == "Invalid token"

    def test_jsonrpc_notification(self):
        """Test JSONRPCNotification model."""
        notification = JSONRPCNotification(
            method="runner/heartbeat",
            params={"timestamp": 1234567890},
        )

        assert notification.jsonrpc == "2.0"
        assert notification.method == "runner/heartbeat"
        assert notification.params == {"timestamp": 1234567890}


@pytest.mark.runner_unit
class TestRunnerMethods:
    """Tests for RunnerMethods constants."""

    def test_runner_to_cp_methods(self):
        """Test Runner → CP method names."""
        assert RunnerMethods.REGISTER == "runner/register"
        assert RunnerMethods.HEARTBEAT == "runner/heartbeat"
        assert RunnerMethods.AVAILABILITY == "runner/availability"
        assert RunnerMethods.TOOL_PROXY == "tool/proxy"
        assert RunnerMethods.WORKFLOW_RESULT == "workflow/result"

    def test_cp_to_runner_methods(self):
        """Test CP → Runner method names."""
        assert RunnerMethods.CONFIG_PUSH == "config/push"
        assert RunnerMethods.WORKFLOW_EXECUTE == "workflow/execute"
        assert RunnerMethods.TOOL_CALL == "tool/call"


@pytest.mark.runner_unit
class TestMCPConfig:
    """Tests for MCPConfig dataclass."""

    def test_create_stdio_config(self):
        """Test creating stdio MCP config."""
        config = MCPConfig(
            name="filesystem",
            command="npx",
            args=["-y", "@anthropic/mcp-server-filesystem"],
            env={"HOME": "/home/user"},
        )

        assert config.name == "filesystem"
        assert config.command == "npx"
        assert config.args == ["-y", "@anthropic/mcp-server-filesystem"]
        assert config.env == {"HOME": "/home/user"}
        assert config.url is None

    def test_create_http_config(self):
        """Test creating HTTP MCP config."""
        config = MCPConfig(
            name="remote-mcp",
            command="",
            url="http://localhost:8080/mcp",
        )

        assert config.name == "remote-mcp"
        assert config.url == "http://localhost:8080/mcp"


@pytest.mark.runner_unit
class TestRunnerMCPConfig:
    """Tests for RunnerMCPConfig dataclass."""

    def test_create_empty_config(self):
        """Test creating empty MCP config."""
        config = RunnerMCPConfig()
        assert config.mcps == {}

    def test_create_with_mcps(self):
        """Test creating config with MCPs."""
        fs_config = MCPConfig(name="filesystem", command="npx")
        docker_config = MCPConfig(name="docker", command="docker-mcp")

        config = RunnerMCPConfig(
            mcps={
                "filesystem": fs_config,
                "docker": docker_config,
            }
        )

        assert len(config.mcps) == 2
        assert "filesystem" in config.mcps
        assert "docker" in config.mcps
