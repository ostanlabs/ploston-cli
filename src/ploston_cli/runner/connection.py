"""WebSocket connection layer for runner-to-CP communication.

Handles:
- WebSocket connection establishment
- Authentication handshake
- Message routing
- Reconnection logic with exponential backoff
- Heartbeat management
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from .types import (
    JSONRPCErrorCode,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    RunnerConfig,
    RunnerConnectionStatus,
    RunnerMethods,
)

logger = logging.getLogger(__name__)

# Type for message handlers
MessageHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]


class RunnerConnection:
    """WebSocket connection to Control Plane.

    Manages the persistent WebSocket connection, handles authentication,
    message routing, and automatic reconnection.
    """

    def __init__(
        self,
        config: RunnerConfig,
        on_config_push: MessageHandler | None = None,
        on_workflow_execute: MessageHandler | None = None,
        on_tool_call: MessageHandler | None = None,
        on_disconnect: Callable[[], Awaitable[None]] | None = None,
    ):
        """Initialize runner connection.

        Args:
            config: Runner configuration with CP URL and auth token
            on_config_push: Handler for config/push messages
            on_workflow_execute: Handler for workflow/execute messages
            on_tool_call: Handler for tool/call messages
            on_disconnect: Callback when connection is lost (runner will exit)
        """
        self._config = config
        self._ws: ClientConnection | None = None
        self._status = RunnerConnectionStatus.DISCONNECTED
        self._request_id = 0
        self._pending_requests: dict[int | str, asyncio.Future[dict[str, Any]]] = {}
        self._reconnect_delay = config.reconnect_delay
        self._should_run = False
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._on_disconnect = on_disconnect

        # Message handlers
        self._handlers: dict[str, MessageHandler] = {}
        if on_config_push:
            self._handlers[RunnerMethods.CONFIG_PUSH] = on_config_push
        if on_workflow_execute:
            self._handlers[RunnerMethods.WORKFLOW_EXECUTE] = on_workflow_execute
        if on_tool_call:
            self._handlers[RunnerMethods.TOOL_CALL] = on_tool_call

    @property
    def status(self) -> RunnerConnectionStatus:
        """Current connection status."""
        return self._status

    @property
    def is_connected(self) -> bool:
        """Whether connection is established."""
        return self._status == RunnerConnectionStatus.CONNECTED

    def _next_request_id(self) -> int:
        """Generate next request ID."""
        self._request_id += 1
        return self._request_id

    async def connect(self) -> None:
        """Establish connection to Control Plane.

        Performs:
        1. WebSocket connection
        2. Authentication handshake (runner/register)
        3. Starts heartbeat and receive loops

        Raises:
            ConnectionError: If connection or auth fails
        """
        if self._status == RunnerConnectionStatus.CONNECTED:
            logger.debug("Already connected")
            return

        self._status = RunnerConnectionStatus.CONNECTING
        self._should_run = True

        try:
            logger.info(f"Connecting to Control Plane at {self._config.control_plane_url}")
            self._ws = await websockets.connect(
                self._config.control_plane_url,
                additional_headers={"Authorization": f"Bearer {self._config.auth_token}"},
            )

            # Start receive loop BEFORE authentication so we can receive the auth response
            self._receive_task = asyncio.create_task(self._receive_loop())

            # Perform authentication handshake
            await self._authenticate()

            self._status = RunnerConnectionStatus.CONNECTED
            self._reconnect_delay = self._config.reconnect_delay  # Reset delay on success

            # Start heartbeat task after successful authentication
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            logger.info(f"Connected to Control Plane as '{self._config.runner_name}'")

        except Exception as e:
            self._status = RunnerConnectionStatus.DISCONNECTED
            logger.error(f"Connection failed: {e}")
            raise ConnectionError(f"Failed to connect to Control Plane: {e}") from e

    async def _authenticate(self) -> None:
        """Perform authentication handshake."""
        response = await self.send_request(
            RunnerMethods.REGISTER,
            {
                "token": self._config.auth_token,
                "name": self._config.runner_name,
            },
        )

        if response.get("error"):
            error = response["error"]
            raise ConnectionError(f"Authentication failed: {error.get('message', 'Unknown error')}")

        logger.debug("Authentication successful")

    async def disconnect(self, timeout: float = 5.0) -> None:
        """Disconnect from Control Plane.

        Args:
            timeout: Maximum time to wait for disconnect in seconds
        """
        self._should_run = False

        # Cancel background tasks with timeout
        async def cancel_task(task: asyncio.Task[Any] | None, name: str) -> None:
            if task:
                task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                except (TimeoutError, asyncio.CancelledError):
                    pass
                except Exception as e:
                    logger.debug(f"Error cancelling {name}: {e}")

        await cancel_task(self._heartbeat_task, "heartbeat")
        self._heartbeat_task = None

        await cancel_task(self._receive_task, "receive")
        self._receive_task = None

        # Close WebSocket with timeout
        if self._ws:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=timeout)
            except TimeoutError:
                logger.warning(f"Timeout ({timeout}s) closing WebSocket")
            except Exception as e:
                logger.debug(f"Error closing WebSocket: {e}")
            self._ws = None

        self._status = RunnerConnectionStatus.DISCONNECTED
        logger.info("Disconnected from Control Plane")

    async def send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send JSON-RPC request and wait for response.

        Args:
            method: JSON-RPC method name
            params: Method parameters
            timeout: Response timeout in seconds

        Returns:
            Response dict with result or error

        Raises:
            ConnectionError: If not connected
            TimeoutError: If response times out
        """
        if not self._ws:
            raise ConnectionError("Not connected to Control Plane")

        request_id = self._next_request_id()
        request = JSONRPCRequest(
            id=request_id,
            method=method,
            params=params or {},
        )

        # Create future for response
        future: asyncio.Future[dict[str, Any]] = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            await self._ws.send(request.model_dump_json())
            logger.debug(f"Sent request: {method} (id={request_id})")

            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=timeout)
            return response

        except TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise TimeoutError(f"Request {method} timed out after {timeout}s")
        except Exception:
            self._pending_requests.pop(request_id, None)
            raise

    async def send_notification(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Send JSON-RPC notification (no response expected).

        Args:
            method: JSON-RPC method name
            params: Method parameters

        Raises:
            ConnectionError: If not connected
        """
        if not self._ws:
            raise ConnectionError("Not connected to Control Plane")

        notification = JSONRPCNotification(
            method=method,
            params=params or {},
        )

        await self._ws.send(notification.model_dump_json())
        logger.debug(f"Sent notification: {method}")

    async def _receive_loop(self) -> None:
        """Background task to receive and route messages."""
        while self._should_run and self._ws:
            try:
                message_str = await self._ws.recv()
                message = json.loads(message_str)
                await self._handle_message(message)

            except websockets.ConnectionClosed:
                logger.warning("Connection closed by server")
                await self._handle_disconnect()
                break
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON received: {e}")
            except Exception as e:
                logger.error(f"Error in receive loop: {e}")

    async def _handle_message(self, message: dict[str, Any]) -> None:
        """Route incoming message to appropriate handler."""
        # Check if it's a response to a pending request
        if "id" in message and message["id"] in self._pending_requests:
            logger.debug(f"<<< RESPONSE [id={message['id']}]: received")
            future = self._pending_requests.pop(message["id"])
            if not future.done():
                future.set_result(message)
            return

        # It's a request or notification from CP
        method = message.get("method")
        request_id = message.get("id", "notification")
        if not method:
            logger.warning(f"Received message without method: {message}")
            return

        logger.debug(f">>> REQUEST [{request_id}] {method}")

        handler = self._handlers.get(method)
        if handler:
            try:
                result = await handler(message.get("params", {}))

                # If it's a request (has id), send response
                if "id" in message and result is not None:
                    response = JSONRPCResponse(
                        id=message["id"],
                        result=result,
                    )
                    logger.debug(f"<<< RESPONSE [{message['id']}] {method}: OK")
                    await self._ws.send(response.model_dump_json(exclude_none=True))

            except Exception as e:
                logger.error(f"Handler error for {method}: {e}")
                if "id" in message:
                    error_response = JSONRPCResponse(
                        id=message["id"],
                        error={
                            "code": JSONRPCErrorCode.INTERNAL_ERROR,
                            "message": str(e),
                        },
                    )
                    logger.debug(f"<<< RESPONSE [{message['id']}] {method}: ERROR - {e}")
                    await self._ws.send(error_response.model_dump_json(exclude_none=True))
        else:
            logger.warning(f"No handler for method: {method}")

    async def _heartbeat_loop(self) -> None:
        """Background task to send periodic heartbeats."""
        while self._should_run:
            try:
                await asyncio.sleep(self._config.heartbeat_interval)
                if self._ws and self._status == RunnerConnectionStatus.CONNECTED:
                    await self.send_notification(
                        RunnerMethods.HEARTBEAT,
                        {"timestamp": time.time()},
                    )
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    async def _handle_disconnect(self) -> None:
        """Handle unexpected disconnection.

        Instead of reconnecting, we exit the runner. This is the expected behavior
        because the runner should be managed by a process supervisor (systemd, etc.)
        that will restart it if needed.
        """
        if not self._should_run:
            return

        self._status = RunnerConnectionStatus.DISCONNECTED
        logger.error("Connection to Control Plane lost. Runner will exit.")

        # Signal that we should stop running
        self._should_run = False

        # Call the disconnect callback if set
        if self._on_disconnect:
            try:
                await self._on_disconnect()
            except Exception as e:
                logger.error(f"Error in disconnect callback: {e}")

    async def run(self) -> None:
        """Run the connection (connect and maintain)."""
        await self.connect()

        # Wait for tasks to complete (they run until disconnect)
        if self._receive_task:
            await self._receive_task
