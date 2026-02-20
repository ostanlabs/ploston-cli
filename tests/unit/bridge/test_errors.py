"""Unit tests for error mapping - HTTP errors to MCP JSON-RPC errors.

TDD RED phase: These tests define the expected error mapping behavior.
All tests should FAIL initially until error mapping is implemented.

Test IDs: UT-B033 to UT-B042
"""

import pytest

# Import will fail until we create the module
try:
    from ploston_cli.bridge.errors import (
        AuthenticationError,
        BridgeError,
        NotFoundError,
        ServerError,
        map_connection_error,
        map_http_error,
    )
    from ploston_cli.bridge.errors import (
        TimeoutError as BridgeTimeoutError,
    )
except ImportError:
    map_http_error = None
    map_connection_error = None
    BridgeError = None
    AuthenticationError = None
    NotFoundError = None
    BridgeTimeoutError = None
    ServerError = None


pytestmark = [pytest.mark.bridge, pytest.mark.bridge_unit]


def skip_if_not_implemented():
    if map_http_error is None:
        pytest.skip("Error mapping not implemented yet")


# =============================================================================
# UT-B033 to UT-B035: Authentication Error Mapping
# =============================================================================


class TestAuthenticationErrorMapping:
    """Tests for HTTP 401/403 to MCP error mapping."""

    def test_ut_b033_http_401_maps_to_auth_error(self):
        """UT-B033: HTTP 401 maps to authentication error code -32001."""
        skip_if_not_implemented()

        error = map_http_error(401, "Unauthorized")

        assert error.code == -32001
        assert "Authentication failed" in error.message
        assert error.retryable is False

    def test_ut_b034_http_403_maps_to_auth_error(self):
        """UT-B034: HTTP 403 maps to authentication error code -32001."""
        skip_if_not_implemented()

        error = map_http_error(403, "Forbidden")

        assert error.code == -32001
        assert "Authentication failed" in error.message or "Forbidden" in error.message
        assert error.retryable is False

    def test_ut_b035_auth_error_includes_details(self):
        """UT-B035: Auth error includes original HTTP details."""
        skip_if_not_implemented()

        error = map_http_error(401, "Invalid token: expired")

        assert (
            "expired" in error.message
            or error.data.get("original_message") == "Invalid token: expired"
        )


# =============================================================================
# UT-B036: Not Found Error Mapping
# =============================================================================


class TestNotFoundErrorMapping:
    """Tests for HTTP 404 to MCP error mapping."""

    def test_ut_b036_http_404_maps_to_method_not_found(self):
        """UT-B036: HTTP 404 maps to method not found error code -32601."""
        skip_if_not_implemented()

        error = map_http_error(404, "Tool not found: nonexistent_tool")

        assert error.code == -32601
        assert "not found" in error.message.lower()
        assert error.retryable is False


# =============================================================================
# UT-B037 to UT-B038: Timeout Error Mapping
# =============================================================================


class TestTimeoutErrorMapping:
    """Tests for HTTP 408/504 to MCP error mapping."""

    def test_ut_b037_http_408_maps_to_timeout_error(self):
        """UT-B037: HTTP 408 maps to timeout error with retryable=True."""
        skip_if_not_implemented()

        error = map_http_error(408, "Request Timeout")

        assert error.code == -32000
        assert error.retryable is True
        assert "timeout" in error.message.lower()

    def test_ut_b038_http_504_maps_to_timeout_error(self):
        """UT-B038: HTTP 504 maps to gateway timeout error with retryable=True."""
        skip_if_not_implemented()

        error = map_http_error(504, "Gateway Timeout")

        assert error.code == -32000
        assert error.retryable is True


# =============================================================================
# UT-B039: Server Error Mapping
# =============================================================================


class TestServerErrorMapping:
    """Tests for HTTP 500 to MCP error mapping."""

    def test_ut_b039_http_500_maps_to_server_error(self):
        """UT-B039: HTTP 500 maps to server error code -32000."""
        skip_if_not_implemented()

        error = map_http_error(500, "Internal Server Error")

        assert error.code == -32000
        assert "Server error" in error.message or "Internal" in error.message
        # 500 errors may or may not be retryable depending on context
        assert isinstance(error.retryable, bool)


# =============================================================================
# UT-B040: Connection Error Mapping
# =============================================================================


class TestConnectionErrorMapping:
    """Tests for connection errors to MCP error mapping."""

    def test_ut_b040_connection_refused_has_clear_message(self):
        """UT-B040: Connection refused error has clear message with URL."""
        skip_if_not_implemented()

        error = map_connection_error("Connection refused", url="http://localhost:8080")

        assert error.code == -32000
        assert "Cannot reach" in error.message or "Connection" in error.message
        assert "localhost:8080" in error.message
        assert error.retryable is True


# =============================================================================
# UT-B041: Timeout Exception Mapping
# =============================================================================


class TestTimeoutExceptionMapping:
    """Tests for timeout exceptions to MCP error mapping."""

    def test_ut_b041_timeout_exception_is_retryable(self):
        """UT-B041: Timeout exceptions map to retryable errors."""
        skip_if_not_implemented()

        error = map_connection_error("Read timed out", url="http://localhost:8080", is_timeout=True)

        assert error.code == -32000
        assert error.retryable is True
        assert "timeout" in error.message.lower()


# =============================================================================
# UT-B042: AEL Error Passthrough
# =============================================================================


class TestAELErrorPassthrough:
    """Tests for passing through structured AEL errors."""

    def test_ut_b042_ael_error_passthrough(self):
        """UT-B042: Structured AEL errors are passed through unchanged."""
        skip_if_not_implemented()

        # AEL returns structured errors in the response body
        ael_error = {
            "code": -32000,
            "message": "Workflow execution failed",
            "data": {
                "workflow": "scrape_and_summarize",
                "step": "scrape",
                "error": "URL not accessible",
                "retryable": True,
            },
        }

        # When CP returns a JSON-RPC error, it should be passed through
        from ploston_cli.bridge.errors import passthrough_jsonrpc_error

        result = passthrough_jsonrpc_error(ael_error)

        assert result["code"] == -32000
        assert result["message"] == "Workflow execution failed"
        assert result["data"]["workflow"] == "scrape_and_summarize"
        assert result["data"]["retryable"] is True
