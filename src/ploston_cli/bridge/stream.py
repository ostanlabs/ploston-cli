"""StreamHandler - Handles streaming responses from CP.

Processes SSE (Server-Sent Events) responses from POST /mcp,
converting progress events to MCP notifications and final
results to JSON-RPC responses.

NOTE: This is client-side ready. Actual streaming depends on
CP implementing streaming support for POST /mcp responses.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class StreamHandler:
    """Handles streaming responses from CP.

    Detects SSE content-type, parses progress events,
    and converts them to MCP notifications.
    """

    def is_streaming_response(self, content_type: Optional[str]) -> bool:
        """Check if response is a streaming SSE response.

        Args:
            content_type: HTTP Content-Type header value

        Returns:
            True if response is text/event-stream
        """
        if not content_type:
            return False
        return content_type.startswith("text/event-stream")

    def parse_event(self, event: Optional[dict]) -> Optional[dict]:
        """Parse an SSE event.

        Args:
            event: Raw event data

        Returns:
            Parsed event or None if empty/invalid
        """
        if not event:
            return None
        if not event.get("type"):
            return None
        return event

    def to_notification(self, event: dict) -> dict:
        """Convert progress event to MCP notification.

        Args:
            event: Progress event with type, step, status

        Returns:
            MCP notifications/message notification
        """
        step = event.get("step", "")
        status = event.get("status", "running")
        level = self.status_to_level(status)

        return {
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {
                "level": level,
                "data": {
                    "message": f"{step} ({status})",
                    "step": step,
                    "status": status,
                },
            },
        }

    def to_result(self, event: dict, request_id: Any) -> dict:
        """Convert result event to JSON-RPC response.

        Args:
            event: Result event with content
            request_id: Original request ID

        Returns:
            JSON-RPC response
        """
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": event.get("content", []),
            },
        }

    def status_to_level(self, status: str) -> str:
        """Map status to notification level.

        Args:
            status: Event status (running, error, failed, etc.)

        Returns:
            Notification level (info, error)
        """
        if status in ("error", "failed"):
            return "error"
        return "info"

    def timeout_error(self, request_id: Any, timeout: float) -> dict:
        """Create timeout error response.

        Args:
            request_id: Original request ID
            timeout: Timeout value in seconds

        Returns:
            JSON-RPC error response
        """
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32000,
                "message": f"Streaming timeout after {timeout}s",
                "data": {"retryable": True},
            },
        }

    def connection_drop_error(self, request_id: Any) -> dict:
        """Create connection drop error response.

        Args:
            request_id: Original request ID

        Returns:
            JSON-RPC error response
        """
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32000,
                "message": "Stream connection dropped",
                "data": {"retryable": True},
            },
        }
