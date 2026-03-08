"""Unit tests for ploston_cli.runner.connection module."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from ploston_cli.runner.connection import RunnerConnection
from ploston_cli.runner.types import (
    RunnerConfig,
    RunnerConnectionStatus,
    RunnerMethods,
)


@pytest.fixture
def runner_config():
    """Create a test runner config."""
    return RunnerConfig(
        control_plane_url="wss://cp.example.com/runner",
        auth_token="test-token",
        runner_name="test-runner",
        reconnect_delay=1.0,
        max_reconnect_delay=5.0,
        heartbeat_interval=10.0,
    )


@pytest.mark.runner_unit
class TestRunnerConnection:
    """Tests for RunnerConnection class."""

    def test_init(self, runner_config):
        """Test connection initialization."""
        connection = RunnerConnection(config=runner_config)

        assert connection.status == RunnerConnectionStatus.DISCONNECTED
        assert not connection.is_connected
        assert connection._config == runner_config

    def test_init_with_handlers(self, runner_config):
        """Test connection with message handlers."""
        config_handler = AsyncMock()
        workflow_handler = AsyncMock()
        tool_handler = AsyncMock()

        connection = RunnerConnection(
            config=runner_config,
            on_config_push=config_handler,
            on_workflow_execute=workflow_handler,
            on_tool_call=tool_handler,
        )

        assert RunnerMethods.CONFIG_PUSH in connection._handlers
        assert RunnerMethods.WORKFLOW_EXECUTE in connection._handlers
        assert RunnerMethods.TOOL_CALL in connection._handlers

    def test_next_request_id(self, runner_config):
        """Test request ID generation."""
        connection = RunnerConnection(config=runner_config)

        id1 = connection._next_request_id()
        id2 = connection._next_request_id()
        id3 = connection._next_request_id()

        assert id1 == 1
        assert id2 == 2
        assert id3 == 3

    @pytest.mark.asyncio
    async def test_send_request_not_connected(self, runner_config):
        """Test send_request raises when not connected."""
        connection = RunnerConnection(config=runner_config)

        with pytest.raises(ConnectionError, match="Not connected"):
            await connection.send_request("test/method", {})

    @pytest.mark.asyncio
    async def test_send_notification_not_connected(self, runner_config):
        """Test send_notification raises when not connected."""
        connection = RunnerConnection(config=runner_config)

        with pytest.raises(ConnectionError, match="Not connected"):
            await connection.send_notification("test/method", {})

    @pytest.mark.asyncio
    async def test_handle_message_response(self, runner_config):
        """Test handling response to pending request."""
        connection = RunnerConnection(config=runner_config)

        # Create a pending request
        future: asyncio.Future = asyncio.Future()
        connection._pending_requests[1] = future

        # Handle response message
        await connection._handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"status": "ok"},
            }
        )

        assert future.done()
        result = future.result()
        assert result["result"] == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_handle_message_request(self, runner_config):
        """Test handling incoming request from CP."""
        handler = AsyncMock(return_value={"status": "ok"})
        connection = RunnerConnection(
            config=runner_config,
            on_config_push=handler,
        )

        # Mock WebSocket
        mock_ws = AsyncMock()
        connection._ws = mock_ws

        # Handle request message
        await connection._handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": RunnerMethods.CONFIG_PUSH,
                "params": {"mcps": {}},
            }
        )

        handler.assert_called_once_with({"mcps": {}})
        mock_ws.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_message_notification(self, runner_config):
        """Test handling notification (no response expected)."""
        handler = AsyncMock(return_value=None)
        connection = RunnerConnection(
            config=runner_config,
            on_config_push=handler,
        )

        # Mock WebSocket
        mock_ws = AsyncMock()
        connection._ws = mock_ws

        # Handle notification (no id)
        await connection._handle_message(
            {
                "jsonrpc": "2.0",
                "method": RunnerMethods.CONFIG_PUSH,
                "params": {"mcps": {}},
            }
        )

        handler.assert_called_once()
        # No response should be sent for notifications
        mock_ws.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_unknown_method(self, runner_config):
        """Test handling message with unknown method."""
        connection = RunnerConnection(config=runner_config)

        # Should not raise, just log warning
        await connection._handle_message(
            {
                "jsonrpc": "2.0",
                "method": "unknown/method",
                "params": {},
            }
        )

    @pytest.mark.asyncio
    async def test_disconnect(self, runner_config):
        """Test disconnection."""
        connection = RunnerConnection(config=runner_config)
        connection._should_run = True
        connection._status = RunnerConnectionStatus.CONNECTED

        # Mock WebSocket
        mock_ws = AsyncMock()
        connection._ws = mock_ws

        # Mock tasks
        connection._heartbeat_task = asyncio.create_task(asyncio.sleep(100))
        connection._receive_task = asyncio.create_task(asyncio.sleep(100))

        await connection.disconnect()

        assert connection.status == RunnerConnectionStatus.DISCONNECTED
        assert connection._ws is None
        mock_ws.close.assert_called_once()


@pytest.mark.runner_unit
class TestConnectionStatus:
    """Tests for connection status transitions."""

    def test_status_enum_values(self):
        """Test status enum has expected values."""
        assert RunnerConnectionStatus.DISCONNECTED.value == "disconnected"
        assert RunnerConnectionStatus.CONNECTING.value == "connecting"
        assert RunnerConnectionStatus.CONNECTED.value == "connected"
        assert RunnerConnectionStatus.RECONNECTING.value == "reconnecting"


@pytest.mark.runner_unit
class TestReconnection:
    """Tests for automatic reconnection on disconnect."""

    @pytest.fixture
    def reconnect_config(self):
        """Config with fast reconnection for tests."""
        return RunnerConfig(
            control_plane_url="wss://cp.example.com/runner",
            auth_token="test-token",
            runner_name="test-runner",
            reconnect_delay=0.01,  # Very fast for tests
            max_reconnect_delay=0.05,
            max_reconnect_attempts=3,
            heartbeat_interval=10.0,
        )

    @pytest.mark.asyncio
    async def test_reconnect_success_on_second_attempt(self, reconnect_config):
        """Reconnection succeeds on 2nd attempt after disconnect."""
        from unittest.mock import patch

        import websockets

        connection = RunnerConnection(config=reconnect_config)
        connection._should_run = True
        connection._status = RunnerConnectionStatus.CONNECTED

        # Track reconnect callback
        reconnect_called = False

        async def on_reconnect():
            nonlocal reconnect_called
            reconnect_called = True

        connection._on_reconnect = on_reconnect

        # Mock websocket that succeeds on 2nd attempt
        attempt_count = 0

        async def mock_connect(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count == 1:
                raise ConnectionError("Connection refused")
            mock_ws = AsyncMock()
            mock_ws.recv = AsyncMock(side_effect=asyncio.CancelledError)
            return mock_ws

        # Mock authenticate to succeed
        connection._authenticate = AsyncMock()

        with patch.object(websockets, "connect", side_effect=mock_connect):
            await connection._handle_disconnect()

        assert connection._status == RunnerConnectionStatus.CONNECTED
        assert reconnect_called is True
        assert attempt_count == 2

    @pytest.mark.asyncio
    async def test_reconnect_exhausted_calls_on_disconnect(self, reconnect_config):
        """All reconnect attempts exhausted → runner exits, on_disconnect called."""
        from unittest.mock import patch

        import websockets

        disconnect_called = False

        async def on_disconnect():
            nonlocal disconnect_called
            disconnect_called = True

        connection = RunnerConnection(
            config=reconnect_config,
            on_disconnect=on_disconnect,
        )
        connection._should_run = True
        connection._status = RunnerConnectionStatus.CONNECTED

        with patch.object(websockets, "connect", side_effect=ConnectionError("Connection refused")):
            await connection._handle_disconnect()

        assert connection._status == RunnerConnectionStatus.DISCONNECTED
        assert connection._should_run is False
        assert disconnect_called is True

    @pytest.mark.asyncio
    async def test_reconnect_fails_pending_requests(self, reconnect_config):
        """Pending requests are failed with ConnectionError during disconnect."""
        connection = RunnerConnection(config=reconnect_config)
        connection._should_run = True
        connection._status = RunnerConnectionStatus.CONNECTED
        connection._config = RunnerConfig(
            control_plane_url="wss://cp.example.com/runner",
            auth_token="test-token",
            runner_name="test-runner",
            reconnect_delay=0.01,
            max_reconnect_delay=0.05,
            max_reconnect_attempts=0,  # No retries — just fail pending
        )

        # Add pending requests
        future1: asyncio.Future = asyncio.Future()
        future2: asyncio.Future = asyncio.Future()
        connection._pending_requests[1] = future1
        connection._pending_requests[2] = future2

        await connection._handle_disconnect()

        assert future1.done()
        assert future2.done()
        with pytest.raises(ConnectionError):
            future1.result()
        with pytest.raises(ConnectionError):
            future2.result()

    @pytest.mark.asyncio
    async def test_reconnect_cancels_heartbeat(self, reconnect_config):
        """Heartbeat is cancelled during reconnection."""
        from unittest.mock import patch

        import websockets

        connection = RunnerConnection(config=reconnect_config)
        connection._should_run = True
        connection._status = RunnerConnectionStatus.CONNECTED

        # Create a heartbeat task
        heartbeat_task = asyncio.create_task(asyncio.sleep(100))
        connection._heartbeat_task = heartbeat_task

        with patch.object(websockets, "connect", side_effect=ConnectionError("Connection refused")):
            await connection._handle_disconnect()

        assert heartbeat_task.cancelled()

    @pytest.mark.asyncio
    async def test_reconnect_not_called_when_should_run_false(self, reconnect_config):
        """No reconnection when _should_run is already False (graceful disconnect)."""
        connection = RunnerConnection(config=reconnect_config)
        connection._should_run = False
        connection._status = RunnerConnectionStatus.CONNECTED

        await connection._handle_disconnect()

        # Status should remain whatever it was — not changed to RECONNECTING
        assert connection._status == RunnerConnectionStatus.CONNECTED
