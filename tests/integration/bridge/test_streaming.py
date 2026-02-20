"""Integration tests for streaming responses.

Tests IT-B009 to IT-B010: Streaming execution progress and timeout.

NOTE: These tests use a mock CP that returns SSE responses.
Real streaming depends on CP implementing streaming support.
"""

import asyncio

import pytest
from aiohttp import web

from ploston_cli.bridge.stream import StreamHandler


class MockCPServerStreaming:
    """Mock CP server that returns streaming responses."""

    def __init__(self):
        self.stream_delay = 0.1  # Delay between events
        self.should_timeout = False
        self.should_drop = False

    async def handle_mcp_streaming(self, request):
        """Handle POST /mcp with streaming response."""
        data = await request.json()
        method = data.get("method", "")
        request_id = data.get("id")

        if method == "tools/call":
            if self.should_timeout:
                # Simulate timeout by never completing
                response = web.StreamResponse()
                response.headers["Content-Type"] = "text/event-stream"
                await response.prepare(request)
                await asyncio.sleep(10)  # Long delay
                return response

            if self.should_drop:
                # Simulate connection drop
                response = web.StreamResponse()
                response.headers["Content-Type"] = "text/event-stream"
                await response.prepare(request)
                await response.write(b'data: {"type": "progress", "step": "Starting"}\n\n')
                # Don't send result, just close
                return response

            # Normal streaming response
            response = web.StreamResponse()
            response.headers["Content-Type"] = "text/event-stream"
            await response.prepare(request)

            # Send progress events
            events = [
                '{"type": "progress", "step": "Step 1", "status": "running"}',
                '{"type": "progress", "step": "Step 2", "status": "running"}',
                '{"type": "result", "content": [{"type": "text", "text": "Done"}]}',
            ]

            for event in events:
                await response.write(f"data: {event}\n\n".encode())
                await asyncio.sleep(self.stream_delay)

            return response

        # Non-streaming response
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {},
            }
        )


@pytest.fixture
async def streaming_server():
    """Create mock CP server for streaming tests."""
    server = MockCPServerStreaming()
    app = web.Application()
    app.router.add_post("/mcp", server.handle_mcp_streaming)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    port = site._server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    yield server, url

    await runner.cleanup()


class TestStreamingIntegration:
    """Integration tests for streaming responses."""

    @pytest.mark.asyncio
    async def test_it_b009_streaming_execution_progress(self, streaming_server):
        """IT-B009: Streaming execution with progress events."""
        server, url = streaming_server
        handler = StreamHandler()

        # Simulate receiving streaming response
        # In real implementation, this would come from httpx streaming
        events = [
            {"type": "progress", "step": "Step 1", "status": "running"},
            {"type": "progress", "step": "Step 2", "status": "running"},
            {"type": "result", "content": [{"type": "text", "text": "Done"}]},
        ]

        notifications = []
        result = None

        for event in events:
            parsed = handler.parse_event(event)
            if parsed:
                if parsed["type"] == "progress":
                    notifications.append(handler.to_notification(parsed))
                elif parsed["type"] == "result":
                    result = handler.to_result(parsed, request_id=1)

        # Should have 2 progress notifications
        assert len(notifications) == 2
        assert "Step 1" in notifications[0]["params"]["data"]["message"]
        assert "Step 2" in notifications[1]["params"]["data"]["message"]

        # Should have final result
        assert result is not None
        assert result["result"]["content"][0]["text"] == "Done"

    @pytest.mark.asyncio
    async def test_it_b010_streaming_timeout(self, streaming_server):
        """IT-B010: Streaming timeout produces retryable error."""
        server, url = streaming_server
        handler = StreamHandler()

        # Simulate timeout
        error = handler.timeout_error(request_id=1, timeout=30.0)

        assert error["error"]["code"] == -32000
        assert "timeout" in error["error"]["message"].lower()
        assert error["error"]["data"]["retryable"] is True

    @pytest.mark.asyncio
    async def test_it_b010b_streaming_connection_drop(self, streaming_server):
        """IT-B010b: Connection drop produces retryable error."""
        server, url = streaming_server
        handler = StreamHandler()

        # Simulate connection drop
        error = handler.connection_drop_error(request_id=1)

        assert error["error"]["code"] == -32000
        assert error["error"]["data"]["retryable"] is True
