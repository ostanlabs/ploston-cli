"""Error mapping for CLI Bridge - HTTP errors to MCP JSON-RPC errors.

Maps HTTP status codes and connection errors to MCP-compliant JSON-RPC errors.
"""

from dataclasses import dataclass, field
from typing import Any

# JSON-RPC error codes
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603
JSONRPC_SERVER_ERROR = -32000  # -32000 to -32099 reserved for implementation-defined server errors

# Custom error codes for bridge
BRIDGE_AUTH_ERROR = -32001
BRIDGE_CONNECTION_ERROR = -32002
BRIDGE_TIMEOUT_ERROR = -32003


@dataclass
class BridgeError(Exception):
    """Base error class for bridge errors."""

    code: int
    message: str
    retryable: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def to_jsonrpc(self) -> dict[str, Any]:
        """Convert to JSON-RPC error object."""
        error = {"code": self.code, "message": self.message}
        if self.data:
            error["data"] = self.data
        return error


@dataclass
class AuthenticationError(BridgeError):
    """Authentication failed (HTTP 401/403)."""

    code: int = BRIDGE_AUTH_ERROR
    message: str = "Authentication failed"
    retryable: bool = False


@dataclass
class NotFoundError(BridgeError):
    """Resource not found (HTTP 404)."""

    code: int = JSONRPC_METHOD_NOT_FOUND
    message: str = "Tool or workflow not found"
    retryable: bool = False


@dataclass
class TimeoutError(BridgeError):
    """Request timeout (HTTP 408/504 or connection timeout)."""

    code: int = JSONRPC_SERVER_ERROR
    message: str = "Request timeout"
    retryable: bool = True


@dataclass
class ServerError(BridgeError):
    """Server error (HTTP 500)."""

    code: int = JSONRPC_SERVER_ERROR
    message: str = "Server error"
    retryable: bool = False


def map_http_error(status_code: int, message: str) -> BridgeError:
    """Map HTTP status code to BridgeError.

    Args:
        status_code: HTTP status code
        message: Error message from response

    Returns:
        Appropriate BridgeError subclass
    """
    if status_code in (401, 403):
        return AuthenticationError(
            message=f"Authentication failed: {message}" if message else "Authentication failed",
            data={"original_message": message, "http_status": status_code},
        )
    elif status_code == 404:
        return NotFoundError(
            message=f"Tool or workflow not found: {message}"
            if message
            else "Tool or workflow not found",
            data={"original_message": message, "http_status": status_code},
        )
    elif status_code in (408, 504):
        return TimeoutError(
            message=f"Request timeout: {message}" if message else "Request timeout",
            data={"original_message": message, "http_status": status_code},
        )
    elif status_code >= 500:
        return ServerError(
            message=f"Server error: {message}" if message else "Server error",
            data={"original_message": message, "http_status": status_code},
            retryable=status_code in (502, 503),  # Gateway errors may be retryable
        )
    else:
        return BridgeError(
            code=JSONRPC_SERVER_ERROR,
            message=f"HTTP error {status_code}: {message}",
            data={"original_message": message, "http_status": status_code},
        )


def map_connection_error(error_message: str, url: str, is_timeout: bool = False) -> BridgeError:
    """Map connection error to BridgeError.

    Args:
        error_message: Error message from exception
        url: URL that was being accessed
        is_timeout: Whether this was a timeout error

    Returns:
        Appropriate BridgeError
    """
    if is_timeout:
        return TimeoutError(
            message=f"Request timeout connecting to {url}",
            data={"url": url, "original_error": error_message},
        )
    else:
        # Extract host:port from URL for clearer message
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host_port = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname

        return BridgeError(
            code=JSONRPC_SERVER_ERROR,
            message=f"Cannot reach Control Plane at {host_port}",
            retryable=True,
            data={"url": url, "original_error": error_message},
        )


def passthrough_jsonrpc_error(error: dict[str, Any]) -> dict[str, Any]:
    """Pass through a JSON-RPC error from CP unchanged.

    Args:
        error: JSON-RPC error object from CP response

    Returns:
        Same error object (for passthrough)
    """
    return error
