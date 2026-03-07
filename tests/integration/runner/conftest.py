"""Pytest fixtures for runner integration tests with Mock CP.

These tests run a real runner process against a mock CP server.
No Docker Compose or K8s backend is needed.
"""

import asyncio
import json
import subprocess
import threading
from collections.abc import Generator

import pytest
from websockets.asyncio.server import serve as ws_serve


class MockControlPlane:
    """Mock Control Plane for testing runner behavior.

    Simulates CP WebSocket server to test runner in isolation.
    """

    def __init__(self, host: str = "localhost", port: int = 18022):
        self.host = host
        self.port = port
        self.server = None
        self.connections: list = []
        self.received_messages: list = []
        self.config_to_push: dict = {}
        self.tool_calls_to_send: list = []
        self._loop = None
        self._thread = None

    async def handler(self, websocket):
        """Handle incoming WebSocket connections."""
        self.connections.append(websocket)
        try:
            # Send config on connection (simulating config push)
            if self.config_to_push:
                await websocket.send(json.dumps({"type": "config", "config": self.config_to_push}))

            # Process messages from runner
            async for message in websocket:
                data = json.loads(message)
                self.received_messages.append(data)

                # If runner reports tools, acknowledge
                if data.get("type") == "tools_report":
                    await websocket.send(json.dumps({"type": "tools_ack", "status": "received"}))

                # Send any pending tool calls
                for tool_call in self.tool_calls_to_send:
                    await websocket.send(json.dumps(tool_call))
                self.tool_calls_to_send.clear()

        finally:
            self.connections.remove(websocket)

    def start(self):
        """Start the mock CP server in a background thread."""

        def run_server():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            async def serve():
                self.server = await ws_serve(self.handler, self.host, self.port)
                await self.server.wait_closed()

            self._loop.run_until_complete(serve())

        self._thread = threading.Thread(target=run_server, daemon=True)
        self._thread.start()
        # Give server time to start
        import time

        time.sleep(0.5)

    def stop(self):
        """Stop the mock CP server."""
        if self.server:
            self.server.close()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def set_config(self, config: dict):
        """Set config to push to runner on connection."""
        self.config_to_push = config

    def queue_tool_call(self, tool_name: str, arguments: dict) -> str:
        """Queue a tool call to send to runner."""
        call_id = f"call_{len(self.tool_calls_to_send)}"
        self.tool_calls_to_send.append(
            {"type": "tool_call", "id": call_id, "tool": tool_name, "arguments": arguments}
        )
        return call_id

    def get_tool_reports(self) -> list:
        """Get all tool reports received from runner."""
        return [m for m in self.received_messages if m.get("type") == "tools_report"]

    def get_tool_results(self) -> list:
        """Get all tool results received from runner."""
        return [m for m in self.received_messages if m.get("type") == "tool_result"]


@pytest.fixture
def mock_cp() -> Generator[MockControlPlane, None, None]:
    """Fixture providing a mock Control Plane server."""
    cp = MockControlPlane()
    cp.start()
    yield cp
    cp.stop()


@pytest.fixture
def start_runner(mock_cp: MockControlPlane) -> Generator[callable, None, None]:
    """Fixture to start a real runner process connecting to mock CP."""
    processes = []

    def _start_runner(token: str = "test_token", name: str = "test-runner") -> subprocess.Popen:
        """Start a runner process."""
        proc = subprocess.Popen(
            [
                "ploston-runner",
                "connect",
                "--token",
                token,
                "--cp-url",
                f"ws://{mock_cp.host}:{mock_cp.port}",
                "--name",
                name,
                "--verbose",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append(proc)
        return proc

    yield _start_runner

    # Cleanup
    for proc in processes:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
