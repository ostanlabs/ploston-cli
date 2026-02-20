"""Unit tests for StreamHandler.

Tests UT-B043 to UT-B052: Streaming response handling.
"""

import pytest

from ploston_cli.bridge.stream import StreamHandler


class TestStreamDetection:
    """Tests for stream detection (UT-B043)."""

    def test_ut_b043_detect_sse_content_type(self):
        """UT-B043: Detect text/event-stream content type."""
        handler = StreamHandler()

        assert handler.is_streaming_response("text/event-stream") is True
        assert handler.is_streaming_response("text/event-stream; charset=utf-8") is True
        assert handler.is_streaming_response("application/json") is False
        assert handler.is_streaming_response(None) is False


class TestProgressParsing:
    """Tests for progress event parsing (UT-B044, UT-B045, UT-B046)."""

    def test_ut_b044_parse_progress_event(self):
        """UT-B044: Parse progress event from SSE."""
        handler = StreamHandler()

        event = {"type": "progress", "step": "Executing workflow", "status": "running"}
        result = handler.parse_event(event)

        assert result["type"] == "progress"
        assert result["step"] == "Executing workflow"
        assert result["status"] == "running"

    def test_ut_b045_forward_progress_as_notification(self):
        """UT-B045: Forward progress as MCP notification."""
        handler = StreamHandler()

        event = {"type": "progress", "step": "Step 1", "status": "running"}
        notification = handler.to_notification(event)

        assert notification["jsonrpc"] == "2.0"
        assert notification["method"] == "notifications/message"
        assert "Step 1" in notification["params"]["data"]["message"]

    def test_ut_b046_final_result_as_response(self):
        """UT-B046: Final result event becomes response."""
        handler = StreamHandler()

        event = {"type": "result", "content": [{"type": "text", "text": "Done"}]}
        result = handler.to_result(event, request_id=1)

        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 1
        assert result["result"]["content"] == [{"type": "text", "text": "Done"}]


class TestMultipleEvents:
    """Tests for multiple progress events (UT-B047)."""

    @pytest.mark.asyncio
    async def test_ut_b047_multiple_progress_events(self):
        """UT-B047: Handle multiple progress events."""
        handler = StreamHandler()

        events = [
            {"type": "progress", "step": "Step 1", "status": "running"},
            {"type": "progress", "step": "Step 2", "status": "running"},
            {"type": "result", "content": [{"type": "text", "text": "Done"}]},
        ]

        notifications = []
        result = None

        for event in events:
            if event["type"] == "progress":
                notifications.append(handler.to_notification(event))
            elif event["type"] == "result":
                result = handler.to_result(event, request_id=1)

        assert len(notifications) == 2
        assert result is not None
        assert result["result"]["content"][0]["text"] == "Done"


class TestErrorHandling:
    """Tests for error handling (UT-B048, UT-B049)."""

    def test_ut_b048_timeout_error(self):
        """UT-B048: Timeout produces retryable error."""
        handler = StreamHandler()

        error = handler.timeout_error(request_id=1, timeout=30.0)

        assert error["jsonrpc"] == "2.0"
        assert error["id"] == 1
        assert error["error"]["code"] == -32000
        assert "timeout" in error["error"]["message"].lower()
        assert error["error"]["data"]["retryable"] is True

    def test_ut_b049_connection_drop_error(self):
        """UT-B049: Connection drop produces retryable error."""
        handler = StreamHandler()

        error = handler.connection_drop_error(request_id=1)

        assert error["jsonrpc"] == "2.0"
        assert error["id"] == 1
        assert error["error"]["code"] == -32000
        assert error["error"]["data"]["retryable"] is True


class TestNotificationLevel:
    """Tests for notification level mapping (UT-B050)."""

    def test_ut_b050_notification_level_mapping(self):
        """UT-B050: Map status to notification level."""
        handler = StreamHandler()

        assert handler.status_to_level("error") == "error"
        assert handler.status_to_level("failed") == "error"
        assert handler.status_to_level("running") == "info"
        assert handler.status_to_level("completed") == "info"
        assert handler.status_to_level("unknown") == "info"


class TestFallback:
    """Tests for fallback to sync (UT-B051)."""

    def test_ut_b051_fallback_to_sync(self):
        """UT-B051: Non-streaming response handled normally."""
        handler = StreamHandler()

        # Regular JSON response (not SSE) - just verify detection works
        # Should pass through unchanged
        assert handler.is_streaming_response("application/json") is False


class TestEmptyEvents:
    """Tests for empty events (UT-B052)."""

    def test_ut_b052_ignore_empty_events(self):
        """UT-B052: Empty events are ignored."""
        handler = StreamHandler()

        assert handler.parse_event({}) is None
        assert handler.parse_event({"type": ""}) is None
        assert handler.parse_event(None) is None
