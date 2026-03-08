"""Unit tests for mcp_extra field extraction in bridge logging.

Tests UT-B080 to UT-B091: Ensure non-standard MCP fields (_meta,
structuredContent, server-specific keys) are surfaced in bridge logs
and never silently dropped by truncation.
"""

from ploston_cli.commands.bridge import _extract_mcp_extra, _format_response_for_log


class TestExtractMcpExtra:
    """Tests for _extract_mcp_extra helper (UT-B080 to UT-B086)."""

    def test_ut_b080_no_extra_fields(self):
        """UT-B080: Standard tool-call result with only content/isError returns None."""
        result = {"content": [{"type": "text", "text": "hello"}], "isError": False}
        assert _extract_mcp_extra(result) is None

    def test_ut_b081_meta_field_extracted(self):
        """UT-B081: _meta field is extracted as extra."""
        result = {
            "content": [{"type": "text", "text": "hello"}],
            "isError": False,
            "_meta": {"requestId": "abc-123"},
        }
        extra = _extract_mcp_extra(result)
        assert extra == {"_meta": {"requestId": "abc-123"}}

    def test_ut_b082_structured_content_extracted(self):
        """UT-B082: structuredContent field is extracted as extra."""
        result = {
            "content": [],
            "isError": False,
            "structuredContent": {"key": "value"},
        }
        extra = _extract_mcp_extra(result)
        assert extra == {"structuredContent": {"key": "value"}}

    def test_ut_b083_multiple_extra_fields(self):
        """UT-B083: Multiple non-standard fields are all extracted."""
        result = {
            "content": [],
            "isError": False,
            "_meta": {"x": 1},
            "structuredContent": {"y": 2},
            "serverSpecific": "custom",
        }
        extra = _extract_mcp_extra(result)
        assert extra == {
            "_meta": {"x": 1},
            "structuredContent": {"y": 2},
            "serverSpecific": "custom",
        }

    def test_ut_b084_non_tool_call_result_returns_none(self):
        """UT-B084: Non-tool-call results (no 'content' key) return None."""
        # tools/list shape
        assert _extract_mcp_extra({"tools": []}) is None
        # initialize shape
        assert _extract_mcp_extra({"protocolVersion": "2024-11-05"}) is None
        # empty dict
        assert _extract_mcp_extra({}) is None

    def test_ut_b085_content_only_no_is_error(self):
        """UT-B085: Result with content but no isError — no extra."""
        result = {"content": [{"type": "text", "text": "ok"}]}
        assert _extract_mcp_extra(result) is None

    def test_ut_b086_content_with_extra_no_is_error(self):
        """UT-B086: Result with content and extra but no isError — extra extracted."""
        result = {"content": [], "_meta": {"foo": "bar"}}
        extra = _extract_mcp_extra(result)
        assert extra == {"_meta": {"foo": "bar"}}


class TestFormatResponseMcpExtra:
    """Tests for mcp_extra in _format_response_for_log (UT-B087 to UT-B091)."""

    def test_ut_b087_extra_appended_to_log(self):
        """UT-B087: mcp_extra is appended to log line when present."""
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [{"type": "text", "text": "ok"}],
                "isError": False,
                "_meta": {"rid": "x"},
            },
        }
        log = _format_response_for_log(response)
        assert "mcp_extra=" in log
        assert '"_meta"' in log
        assert log.startswith("[1] OK:")

    def test_ut_b088_no_extra_no_suffix(self):
        """UT-B088: No mcp_extra suffix when result has only standard fields."""
        response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{"type": "text", "text": "ok"}],
                "isError": False,
            },
        }
        log = _format_response_for_log(response)
        assert "mcp_extra" not in log

    def test_ut_b089_tools_list_no_extra(self):
        """UT-B089: tools/list result does not produce mcp_extra."""
        response = {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"tools": [{"name": "t1", "description": "d"}]},
        }
        log = _format_response_for_log(response)
        assert "mcp_extra" not in log

    def test_ut_b090_error_response_unchanged(self):
        """UT-B090: Error responses are unaffected by mcp_extra logic."""
        response = {
            "jsonrpc": "2.0",
            "id": 4,
            "error": {"code": -32000, "message": "fail"},
        }
        log = _format_response_for_log(response)
        assert "ERROR" in log
        assert "mcp_extra" not in log

    def test_ut_b091_extra_survives_truncation(self):
        """UT-B091: mcp_extra is logged even when main result is truncated."""
        big_text = "x" * 1000
        response = {
            "jsonrpc": "2.0",
            "id": 5,
            "result": {
                "content": [{"type": "text", "text": big_text}],
                "isError": False,
                "_meta": {"important": True},
            },
        }
        log = _format_response_for_log(response)
        # Main result should be truncated
        assert "..." in log
        # But mcp_extra must still be present and complete
        assert 'mcp_extra={"_meta": {"important": true}}' in log
