"""Shared test fixtures for ploston-cli tests.

This module provides fixtures for testing the bridge functionality:
- MockCP: Simulates a Ploston Control Plane with MCP endpoints
- MockAgent: Simulates a stdio MCP client (like Claude Desktop)
- mock_cp_server: Real HTTP server fixture for integration tests
"""

import asyncio
import json
import threading
import time
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass, field
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

# =============================================================================
# Mock CP (Control Plane) - Simulates server-side MCP endpoints
# =============================================================================


@dataclass
class MockCPState:
    """State for MockCP to track requests and configure responses."""

    # Request tracking
    requests: list[dict[str, Any]] = field(default_factory=list)
    sse_connections: int = 0

    # Response configuration
    health_response: dict[str, Any] = field(
        default_factory=lambda: {"status": "ok", "version": "1.0.0"}
    )
    initialize_response: dict[str, Any] = field(
        default_factory=lambda: {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "ploston-cp", "version": "1.0.0"},
            },
        }
    )
    tools_list_response: dict[str, Any] = field(
        default_factory=lambda: {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {
                        "name": "test_tool",
                        "description": "A test tool",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "workflow:test_workflow",
                        "description": "A test workflow",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"input": {"type": "string"}},
                        },
                    },
                ]
            },
        }
    )
    tools_call_response: dict[str, Any] | None = None  # Set per-test
    error_response: dict[str, Any] | None = None  # Force error responses

    # SSE events to emit
    sse_events: list[dict[str, Any]] = field(default_factory=list)

    # Behavior flags
    should_fail_health: bool = False
    health_fail_count: int = 0  # Number of times to fail before succeeding
    should_timeout: bool = False
    timeout_seconds: float = 30.0
    auth_required: bool = False
    expected_token: str = "plt_test_token"

    def reset(self) -> None:
        """Reset state between tests."""
        self.requests.clear()
        self.sse_connections = 0
        self.sse_events.clear()
        self.should_fail_health = False
        self.health_fail_count = 0
        self.should_timeout = False
        self.error_response = None
        self.tools_call_response = None


class MockCP:
    """Mock Control Plane that simulates MCP HTTP+SSE endpoints.

    Provides:
    - POST /mcp - JSON-RPC MCP requests
    - GET /mcp/sse - Server-sent events for notifications
    - GET /health - Health check endpoint
    """

    def __init__(self, state: MockCPState | None = None):
        self.state = state or MockCPState()
        self._health_fail_counter = 0

    async def handle_health(self, request: Any) -> dict[str, Any]:
        """Handle GET /health requests."""
        # Check auth if required
        if self.state.auth_required:
            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                return {"status_code": 401, "body": {"error": "Unauthorized"}}
            token = auth_header[7:]
            if token != self.state.expected_token:
                return {"status_code": 403, "body": {"error": "Forbidden"}}

        # Handle failure scenarios
        if self.state.should_fail_health:
            return {"status_code": 503, "body": {"error": "Service unavailable"}}

        if self.state.health_fail_count > 0:
            self._health_fail_counter += 1
            if self._health_fail_counter <= self.state.health_fail_count:
                return {"status_code": 503, "body": {"error": "Service unavailable"}}

        return {"status_code": 200, "body": self.state.health_response}

    async def handle_mcp(self, request: Any, body: dict[str, Any]) -> dict[str, Any]:
        """Handle POST /mcp JSON-RPC requests."""
        # Track request
        self.state.requests.append(body)

        # Check auth if required
        if self.state.auth_required:
            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                return {"status_code": 401, "body": {"error": "Unauthorized"}}
            token = auth_header[7:]
            if token != self.state.expected_token:
                return {"status_code": 403, "body": {"error": "Forbidden"}}

        # Handle timeout simulation
        if self.state.should_timeout:
            await asyncio.sleep(self.state.timeout_seconds)

        # Handle forced error
        if self.state.error_response:
            return {"status_code": 200, "body": self.state.error_response}

        # Route by method
        method = body.get("method", "")
        request_id = body.get("id", 1)

        if method == "initialize":
            response = self.state.initialize_response.copy()
            response["id"] = request_id
            return {"status_code": 200, "body": response}

        elif method == "tools/list":
            response = self.state.tools_list_response.copy()
            response["id"] = request_id
            return {"status_code": 200, "body": response}

        elif method == "tools/call":
            if self.state.tools_call_response:
                response = self.state.tools_call_response.copy()
                response["id"] = request_id
                return {"status_code": 200, "body": response}
            # Default success response
            return {
                "status_code": 200,
                "body": {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [{"type": "text", "text": "Tool executed"}]},
                },
            }

        else:
            return {
                "status_code": 200,
                "body": {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                },
            }

    async def handle_sse(self, request: Any) -> AsyncGenerator[str, None]:
        """Handle GET /mcp/sse - yields SSE events."""
        self.state.sse_connections += 1

        # Check auth if required
        if self.state.auth_required:
            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                yield 'event: error\ndata: {"error": "Unauthorized"}\n\n'
                return

        # Emit configured events
        for event in self.state.sse_events:
            event_type = event.get("type", "message")
            data = json.dumps(event.get("data", {}))
            yield f"event: {event_type}\ndata: {data}\n\n"
            await asyncio.sleep(0.01)  # Small delay between events

        # Keep connection open with heartbeats
        while True:
            yield "event: heartbeat\ndata: {}\n\n"
            await asyncio.sleep(1)


@pytest.fixture
def mock_cp_state() -> MockCPState:
    """Fixture providing MockCP state for configuration."""
    return MockCPState()


@pytest.fixture
def mock_cp(mock_cp_state: MockCPState) -> MockCP:
    """Fixture providing a MockCP instance."""
    return MockCP(mock_cp_state)


# =============================================================================
# Mock Agent - Simulates stdio MCP client (like Claude Desktop)
# =============================================================================


@dataclass
class MockAgentState:
    """State for MockAgent to track messages and configure behavior."""

    # Messages sent/received
    sent_messages: list[dict[str, Any]] = field(default_factory=list)
    received_messages: list[dict[str, Any]] = field(default_factory=list)
    received_notifications: list[dict[str, Any]] = field(default_factory=list)

    # Request ID counter
    next_id: int = 1

    def reset(self) -> None:
        """Reset state between tests."""
        self.sent_messages.clear()
        self.received_messages.clear()
        self.received_notifications.clear()
        self.next_id = 1


class MockAgent:
    """Mock MCP client that simulates stdio communication.

    Simulates an agent like Claude Desktop that communicates via stdio.
    """

    def __init__(self, state: MockAgentState | None = None):
        self.state = state or MockAgentState()
        self._stdin_queue: asyncio.Queue[str] = asyncio.Queue()
        self._stdout_lines: list[str] = []

    def get_next_id(self) -> int:
        """Get next request ID."""
        id_ = self.state.next_id
        self.state.next_id += 1
        return id_

    def create_initialize_request(self) -> dict[str, Any]:
        """Create an initialize request."""
        return {
            "jsonrpc": "2.0",
            "id": self.get_next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mock-agent", "version": "1.0.0"},
            },
        }

    def create_tools_list_request(self) -> dict[str, Any]:
        """Create a tools/list request."""
        return {
            "jsonrpc": "2.0",
            "id": self.get_next_id(),
            "method": "tools/list",
            "params": {},
        }

    def create_tools_call_request(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Create a tools/call request."""
        return {
            "jsonrpc": "2.0",
            "id": self.get_next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }

    async def send(self, message: dict[str, Any]) -> None:
        """Send a message (simulates writing to bridge's stdin)."""
        self.state.sent_messages.append(message)
        await self._stdin_queue.put(json.dumps(message))

    async def receive(self, timeout: float = 5.0) -> dict[str, Any]:
        """Receive a message (simulates reading from bridge's stdout)."""
        # In real tests, this would read from the bridge process stdout
        # For unit tests, we'll use a mock
        raise NotImplementedError("Use mock in unit tests")

    def write_to_stdin(self, line: str) -> None:
        """Write a line to simulated stdin."""
        self._stdin_queue.put_nowait(line)

    def get_stdout_lines(self) -> list[str]:
        """Get lines written to simulated stdout."""
        return self._stdout_lines.copy()


@pytest.fixture
def mock_agent_state() -> MockAgentState:
    """Fixture providing MockAgent state."""
    return MockAgentState()


@pytest.fixture
def mock_agent(mock_agent_state: MockAgentState) -> MockAgent:
    """Fixture providing a MockAgent instance."""
    return MockAgent(mock_agent_state)


# =============================================================================
# Integration Test Fixtures - Real HTTP Server
# =============================================================================


def create_mock_cp_app(state: MockCPState) -> Any:
    """Create a FastAPI app that simulates CP endpoints."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, StreamingResponse

    app = FastAPI()
    mock_cp = MockCP(state)

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        result = await mock_cp.handle_health(request)
        return JSONResponse(content=result["body"], status_code=result.get("status_code", 200))

    @app.post("/mcp")
    async def mcp(request: Request) -> JSONResponse:
        body = await request.json()
        result = await mock_cp.handle_mcp(request, body)
        return JSONResponse(content=result["body"], status_code=result.get("status_code", 200))

    @app.get("/mcp/sse")
    async def mcp_sse(request: Request) -> StreamingResponse:
        return StreamingResponse(
            mock_cp.handle_sse(request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    return app


@pytest.fixture
async def mock_cp_client(mock_cp_state: MockCPState) -> AsyncGenerator[AsyncClient, None]:
    """Fixture providing an async HTTP client connected to mock CP.

    Uses ASGI transport for in-process testing (no real network).
    """
    app = create_mock_cp_app(mock_cp_state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_cp_server(mock_cp_state: MockCPState) -> Generator[str, None, None]:
    """Fixture that runs a real HTTP server for integration tests.

    Returns the server URL (e.g., "http://localhost:8765").
    """
    import uvicorn

    app = create_mock_cp_app(mock_cp_state)
    port = 8765  # Fixed port for tests

    # Run server in background thread
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to start
    time.sleep(0.5)

    yield f"http://127.0.0.1:{port}"

    # Server will be killed when thread is daemon


# =============================================================================
# Helper Fixtures
# =============================================================================


@pytest.fixture
def sample_mcp_tools() -> list[dict[str, Any]]:
    """Sample MCP tools for testing."""
    return [
        {
            "name": "test_tool",
            "description": "A simple test tool",
            "inputSchema": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        },
        {
            "name": "workflow:scrape_and_summarize",
            "description": "Scrape a URL and summarize content",
            "inputSchema": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    ]


@pytest.fixture
def sample_tool_call_result() -> dict[str, Any]:
    """Sample successful tool call result."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{"type": "text", "text": "Tool executed successfully"}],
            "isError": False,
        },
    }


@pytest.fixture
def sample_tool_call_error() -> dict[str, Any]:
    """Sample tool call error result."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{"type": "text", "text": "Tool execution failed: timeout"}],
            "isError": True,
        },
    }


# =============================================================================
# CLI Test Fixtures - For init --import scenarios
# =============================================================================


@dataclass
class CLIResult:
    """Result from CLI invocation."""

    returncode: int
    stdout: str
    stderr: str


@pytest.fixture
def cli(tmp_path):
    """Fixture providing a CLI runner function.

    Returns a function that runs ploston CLI commands and returns CLIResult.
    """
    import subprocess

    def run_cli(*args, check: bool = True, timeout: int = 30) -> CLIResult:
        """Run ploston CLI with given arguments."""
        result = subprocess.run(
            ["ploston", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(tmp_path),
        )
        cli_result = CLIResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        if check and result.returncode != 0:
            # Don't raise for expected failures
            pass
        return cli_result

    return run_cli


@pytest.fixture
def mock_claude_config(tmp_path, monkeypatch):
    """Create a mock Claude Desktop config for testing.

    Sets up a temporary HOME with a Claude Desktop config file.
    """
    import platform

    # Create config directory based on platform
    if platform.system() == "Darwin":
        config_dir = tmp_path / "Library" / "Application Support" / "Claude"
    else:
        config_dir = tmp_path / ".config" / "Claude"

    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "claude_desktop_config.json"

    # Write sample config with MCP servers
    config_content = {
        "mcpServers": {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            },
            "memory": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-memory"],
            },
        }
    }
    config_file.write_text(json.dumps(config_content, indent=2))

    # Set HOME to temp path
    monkeypatch.setenv("HOME", str(tmp_path))
    if platform.system() != "Darwin":
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))

    return config_file


@pytest.fixture
def cp_url():
    """URL for Control Plane in Docker Compose environment.

    Returns the default CP URL. Tests marked with @pytest.mark.docker
    require the CP to be running.
    """
    import os

    return os.environ.get("PLOSTON_CP_URL", "http://localhost:8080")


@pytest.fixture
def api_url(cp_url):
    """API URL for Control Plane REST endpoints."""
    return f"{cp_url}/api/v1"
