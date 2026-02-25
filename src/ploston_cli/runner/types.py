"""Type definitions for the runner module.

Contains data models, enums, and JSON-RPC message types used by the runner.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RunnerConnectionStatus(StrEnum):
    """Runner connection status."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class RunnerState(StrEnum):
    """Runner connection state (alias for RunnerConnectionStatus)."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    READY = "ready"
    ERROR = "error"


class MCPStatus(StrEnum):
    """MCP server availability status."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class RunnerMethods:
    """JSON-RPC methods for runner communication."""

    # Runner → CP
    REGISTER = "runner/register"
    HEARTBEAT = "runner/heartbeat"
    AVAILABILITY = "runner/availability"
    TOOL_PROXY = "tool/proxy"
    WORKFLOW_RESULT = "workflow/result"

    # CP → Runner
    CONFIG_PUSH = "config/push"
    WORKFLOW_EXECUTE = "workflow/execute"
    TOOL_CALL = "tool/call"


class JSONRPCErrorCode:
    """Standard JSON-RPC 2.0 error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # Custom error codes for runner
    AUTH_FAILED = -32000
    RUNNER_NOT_FOUND = -32001
    TOOL_UNAVAILABLE = -32002
    WORKFLOW_FAILED = -32003
    CONFIG_INVALID = -32004


@dataclass
class ToolInfo:
    """Information about an available tool."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPConfig:
    """Configuration for an MCP server."""

    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None


@dataclass
class MCPAvailability:
    """Availability status for an MCP server."""

    name: str
    status: MCPStatus
    tools: list[ToolInfo] = field(default_factory=list)
    error: str | None = None
    last_checked: datetime | None = None


@dataclass
class RunnerMCPConfig:
    """MCP configuration received from Control Plane."""

    mcps: dict[str, MCPConfig] = field(default_factory=dict)


@dataclass
class RunnerConfig:
    """Bootstrap configuration for runner.

    Minimal config needed to connect to Control Plane.
    Full MCP configs are pushed from CP after connection.
    """

    control_plane_url: str
    auth_token: str
    runner_name: str
    reconnect_delay: float = 5.0
    max_reconnect_delay: float = 60.0
    heartbeat_interval: float = 30.0
    health_check_interval: float = 30.0


@dataclass
class RunnerStatus:
    """Current runner status."""

    name: str
    connection_status: RunnerConnectionStatus
    available_mcps: list[MCPAvailability] = field(default_factory=list)
    unavailable_mcps: list[MCPAvailability] = field(default_factory=list)
    last_heartbeat: datetime | None = None
    uptime_seconds: float = 0.0


# JSON-RPC 2.0 Message Types using Pydantic


class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 request message."""

    jsonrpc: str = "2.0"
    id: int | str
    method: str
    params: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return self.model_dump()


class JSONRPCResponse(BaseModel):
    """JSON-RPC 2.0 response message."""

    jsonrpc: str = "2.0"
    id: int | str | None
    result: Any | None = None
    error: dict[str, Any] | None = None

    model_config = {"exclude_none": True}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return self.model_dump(exclude_none=True)


class JSONRPCNotification(BaseModel):
    """JSON-RPC 2.0 notification (no id, no response expected)."""

    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return self.model_dump()


# Union type for any JSON-RPC message
JSONRPCMessage = JSONRPCRequest | JSONRPCResponse | JSONRPCNotification
