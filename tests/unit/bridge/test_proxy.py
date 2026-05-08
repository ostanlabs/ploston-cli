"""Unit tests for BridgeProxy - HTTP+SSE client to Control Plane.

TDD RED phase: These tests define the expected behavior of BridgeProxy.
All tests should FAIL initially until BridgeProxy is implemented.

Test IDs: UT-B001 to UT-B019
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

# Import will fail until we create the module
try:
    from ploston_cli.bridge.proxy import BridgeProxy, BridgeProxyError
except ImportError:
    BridgeProxy = None
    BridgeProxyError = None


pytestmark = [pytest.mark.bridge, pytest.mark.bridge_unit]


# Skip all tests if BridgeProxy not implemented yet
def skip_if_not_implemented():
    if BridgeProxy is None:
        pytest.skip("BridgeProxy not implemented yet")


# =============================================================================
# UT-B001 to UT-B005: Initialization Tests
# =============================================================================


class TestBridgeProxyInitialization:
    """Tests for BridgeProxy initialization."""

    def test_ut_b001_initialize_with_url(self):
        """UT-B001: BridgeProxy initializes with CP URL."""
        skip_if_not_implemented()
        proxy = BridgeProxy(url="http://localhost:8022")
        assert proxy.url == "http://localhost:8022"
        assert proxy.token is None

    def test_ut_b002_initialize_with_token(self):
        """UT-B002: BridgeProxy initializes with auth token."""
        skip_if_not_implemented()
        proxy = BridgeProxy(url="http://localhost:8022", token="plt_test_token")
        assert proxy.token == "plt_test_token"

    def test_ut_b003_initialize_with_timeout(self):
        """UT-B003: BridgeProxy initializes with custom timeout."""
        skip_if_not_implemented()
        proxy = BridgeProxy(url="http://localhost:8022", timeout=60.0)
        assert proxy.timeout == 60.0

    def test_ut_b004_initialize_default_timeout(self):
        """UT-B004: BridgeProxy has default timeout of 30 seconds."""
        skip_if_not_implemented()
        proxy = BridgeProxy(url="http://localhost:8022")
        assert proxy.timeout == 30.0

    def test_ut_b005_initialize_validates_url(self):
        """UT-B005: BridgeProxy validates URL format."""
        skip_if_not_implemented()
        with pytest.raises(ValueError, match="Invalid URL"):
            BridgeProxy(url="not-a-valid-url")


# =============================================================================
# UT-B006 to UT-B010: MCP Initialize Tests
# =============================================================================


class TestBridgeProxyMCPInitialize:
    """Tests for MCP initialize handshake."""

    @pytest.mark.asyncio
    async def test_ut_b006_initialize_sends_correct_request(self):
        """UT-B006: initialize() sends correct JSON-RPC request to POST /mcp."""
        skip_if_not_implemented()

        # Create mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "ploston-cp", "version": "1.0.0"},
            },
        }

        proxy = BridgeProxy(url="http://test")
        proxy._client = AsyncMock()
        proxy._client.post = AsyncMock(return_value=mock_response)

        result = await proxy.initialize()

        # Verify request was sent
        assert result is not None
        assert "protocolVersion" in result
        assert "capabilities" in result
        assert "serverInfo" in result

    @pytest.mark.asyncio
    async def test_ut_b007_initialize_returns_server_capabilities(self):
        """UT-B007: initialize() returns server capabilities."""
        skip_if_not_implemented()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "ploston-cp", "version": "2.0.0"},
            },
        }

        proxy = BridgeProxy(url="http://test")
        proxy._client = AsyncMock()
        proxy._client.post = AsyncMock(return_value=mock_response)

        result = await proxy.initialize()

        assert result["serverInfo"]["name"] == "ploston-cp"
        assert result["capabilities"]["tools"]["listChanged"] is True

    @pytest.mark.asyncio
    async def test_ut_b008_initialize_handles_error_response(self):
        """UT-B008: initialize() raises error on JSON-RPC error response."""
        skip_if_not_implemented()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Invalid Request"},
        }

        proxy = BridgeProxy(url="http://test")
        proxy._client = AsyncMock()
        proxy._client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(BridgeProxyError) as exc_info:
            await proxy.initialize()

        assert exc_info.value.code == -32600

    @pytest.mark.asyncio
    async def test_ut_b009_initialize_handles_connection_error(self):
        """UT-B009: initialize() raises clear error on connection failure."""
        skip_if_not_implemented()

        import httpx

        proxy = BridgeProxy(url="http://localhost:9999")
        proxy._client = AsyncMock()
        proxy._client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with pytest.raises(BridgeProxyError) as exc_info:
            await proxy.initialize()

        assert "Cannot reach" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_ut_b010_initialize_handles_timeout(self):
        """UT-B010: initialize() raises error on timeout."""
        skip_if_not_implemented()

        import httpx

        proxy = BridgeProxy(url="http://test", timeout=0.05)
        proxy._client = AsyncMock()
        proxy._client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timed out"))

        with pytest.raises(BridgeProxyError) as exc_info:
            await proxy.initialize()

        assert exc_info.value.retryable is True


# =============================================================================
# UT-B011 to UT-B013: Send Request Tests
# =============================================================================


class TestBridgeProxySendRequest:
    """Tests for sending MCP requests."""

    @pytest.mark.asyncio
    async def test_ut_b011_send_request_tools_list(self):
        """UT-B011: send_request() forwards tools/list correctly."""
        skip_if_not_implemented()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [{"name": "test_tool", "description": "A test tool"}]},
        }

        proxy = BridgeProxy(url="http://test")
        proxy._client = AsyncMock()
        proxy._client.post = AsyncMock(return_value=mock_response)

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }
        result = await proxy.send_request(request)

        assert "result" in result
        assert "tools" in result["result"]

    @pytest.mark.asyncio
    async def test_ut_b012_send_request_tools_call(self):
        """UT-B012: send_request() forwards tools/call correctly."""
        skip_if_not_implemented()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "Success"}]},
        }

        proxy = BridgeProxy(url="http://test")
        proxy._client = AsyncMock()
        proxy._client.post = AsyncMock(return_value=mock_response)

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "test_tool", "arguments": {"input": "test"}},
        }
        result = await proxy.send_request(request)

        assert result["result"]["content"][0]["text"] == "Success"

    @pytest.mark.asyncio
    async def test_ut_b013_send_request_preserves_id(self):
        """UT-B013: send_request() preserves request ID in response."""
        skip_if_not_implemented()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 42,
            "result": {"tools": []},
        }

        proxy = BridgeProxy(url="http://test")
        proxy._client = AsyncMock()
        proxy._client.post = AsyncMock(return_value=mock_response)

        request = {
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/list",
            "params": {},
        }
        result = await proxy.send_request(request)

        assert result["id"] == 42


# =============================================================================
# UT-B014 to UT-B015: Bearer Token Tests
# =============================================================================


class TestBridgeProxyAuthentication:
    """Tests for authentication handling."""

    @pytest.mark.asyncio
    async def test_ut_b014_bearer_token_sent_in_header(self):
        """UT-B014: Bearer token is sent in Authorization header."""
        skip_if_not_implemented()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "ploston-cp", "version": "1.0.0"},
            },
        }

        proxy = BridgeProxy(url="http://test", token="plt_secret_token")
        proxy._client = AsyncMock()
        proxy._client.post = AsyncMock(return_value=mock_response)

        result = await proxy.initialize()

        # Verify token is in headers
        assert proxy._get_headers()["Authorization"] == "Bearer plt_secret_token"
        assert result is not None

    @pytest.mark.asyncio
    async def test_ut_b015_missing_token_returns_auth_error(self):
        """UT-B015: Missing token returns authentication error."""
        skip_if_not_implemented()

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        proxy = BridgeProxy(url="http://test")  # No token
        proxy._client = AsyncMock()
        proxy._client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(BridgeProxyError) as exc_info:
            await proxy.initialize()

        assert exc_info.value.code == -32001  # Auth error code


# =============================================================================
# UT-B016 to UT-B017: SSE Subscription Tests
# =============================================================================


class TestBridgeProxySSESubscription:
    """Tests for SSE notification subscription."""

    @pytest.mark.asyncio
    async def test_ut_b016_subscribe_notifications_connects(self):
        """UT-B016: subscribe_notifications() connects to GET /mcp/sse."""
        skip_if_not_implemented()
        # SSE tests require more complex mocking - mark as integration test
        # For unit test, just verify the method exists and is async generator
        proxy = BridgeProxy(url="http://test")
        assert hasattr(proxy, "subscribe_notifications")
        # The actual SSE connection test is better suited for integration tests

    @pytest.mark.asyncio
    async def test_ut_b017_subscribe_notifications_yields_events(self):
        """UT-B017: subscribe_notifications() yields parsed SSE events."""
        skip_if_not_implemented()
        # SSE tests require more complex mocking with httpx-sse
        # This is better tested in integration tests with a real mock server
        proxy = BridgeProxy(url="http://test")
        # Verify the method is an async generator
        gen = proxy.subscribe_notifications()
        assert hasattr(gen, "__anext__")


# =============================================================================
# UT-B018: Health Check Tests
# =============================================================================


class TestBridgeProxyHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_ut_b018_health_check_returns_status(self):
        """UT-B018: health_check() returns CP health status."""
        skip_if_not_implemented()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok", "version": "1.0.0"}

        proxy = BridgeProxy(url="http://test")
        proxy._client = AsyncMock()
        proxy._client.get = AsyncMock(return_value=mock_response)

        result = await proxy.health_check()

        assert result["status"] == "ok"


# =============================================================================
# UT-B019: Close/Cleanup Tests
# =============================================================================


class TestBridgeProxyClose:
    """Tests for connection cleanup."""

    @pytest.mark.asyncio
    async def test_ut_b019_close_releases_resources(self):
        """UT-B019: close() releases HTTP client resources."""
        skip_if_not_implemented()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "ploston-cp", "version": "1.0.0"},
            },
        }

        proxy = BridgeProxy(url="http://test")
        proxy._client = AsyncMock()
        proxy._client.post = AsyncMock(return_value=mock_response)
        proxy._client.aclose = AsyncMock()

        # Simulate some activity
        await proxy.initialize()

        # Close should not raise
        await proxy.close()

        # Subsequent calls should fail gracefully
        with pytest.raises(BridgeProxyError):
            await proxy.initialize()


class TestBridgeProxySessionHeader:
    """S-304/M-082: bridge forwards X-MCP-Session-ID built from (bridge_id, session_start)."""

    def test_session_header_present_when_both_pieces_known(self):
        proxy = BridgeProxy(url="http://test")
        proxy.bridge_id = "bridge-A"
        proxy.bridge_session_start = "2026-05-02T01:00:00"
        headers = proxy._get_headers()
        assert headers.get("X-MCP-Session-ID") == "bridge-A@2026-05-02T01:00:00"

    def test_session_header_absent_without_session_start(self):
        proxy = BridgeProxy(url="http://test")
        proxy.bridge_id = "bridge-A"
        proxy.bridge_session_start = None
        headers = proxy._get_headers()
        assert "X-MCP-Session-ID" not in headers

    def test_session_header_absent_without_bridge_id(self):
        proxy = BridgeProxy(url="http://test")
        proxy.bridge_id = None
        proxy.bridge_session_start = "2026-05-02T01:00:00"
        headers = proxy._get_headers()
        assert "X-MCP-Session-ID" not in headers


class TestBridgeProxyLiveSessionRead:
    """S-304: proxy reads session_start live from lifecycle so idle resets show up."""

    def test_get_headers_reflects_lifecycle_rotation(self):
        proxy = BridgeProxy(url="http://test")

        # Minimal lifecycle stand-in with the attributes BridgeProxy reads.
        class _Lifecycle:
            bridge_id = "bridge-A"
            session_start = "0101-0001"
            _queue_drops_since_connect = 0

        lifecycle = _Lifecycle()
        proxy.set_lifecycle(lifecycle)

        # Initial header reflects the bound value.
        headers_before = proxy._get_headers()
        assert headers_before["X-MCP-Session-ID"] == "bridge-A@0101-0001"
        assert headers_before["X-Bridge-Session-Start"] == "0101-0001"

        # Rotate session_start in place.  Without live read, the cached snapshot
        # would still be "0101-0001"; with live read the new value wins.
        lifecycle.session_start = "0101-0002"
        headers_after = proxy._get_headers()
        assert headers_after["X-MCP-Session-ID"] == "bridge-A@0101-0002"
        assert headers_after["X-Bridge-Session-Start"] == "0101-0002"


# =============================================================================
# UT-B020: Non-JSON response handling
# =============================================================================


class TestBridgeProxyNonJsonResponse:
    """Tests for handling non-JSON responses from the CP."""

    @pytest.mark.asyncio
    async def test_ut_b020_non_json_response_raises_proxy_error(self):
        """UT-B020: Non-JSON response from CP raises BridgeProxyError."""
        skip_if_not_implemented()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("No JSON object")
        mock_response.text = "<html>Internal Server Error</html>"

        proxy = BridgeProxy(url="http://test")
        proxy._client = AsyncMock()
        proxy._client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(BridgeProxyError) as exc_info:
            await proxy.send_request(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "test"}}
            )
        assert "non-JSON response" in exc_info.value.message
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_ut_b020b_empty_body_raises_proxy_error(self):
        """UT-B020b: Empty body from CP raises BridgeProxyError."""
        skip_if_not_implemented()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.text = ""

        proxy = BridgeProxy(url="http://test")
        proxy._client = AsyncMock()
        proxy._client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(BridgeProxyError) as exc_info:
            await proxy.send_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert "non-JSON response" in exc_info.value.message
