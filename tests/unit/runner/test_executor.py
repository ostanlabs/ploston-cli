"""Unit tests for ploston_cli.runner.executor — handle_tool_call parameter passing.

Regression tests for BUG-001: All MCP tool parameters arriving as `undefined`.
The root cause was a key mismatch: CP sends "arguments" but executor read "args".
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ploston_cli.runner.executor import WorkflowExecutor


def _make_executor(
    *,
    mcp_manager: MagicMock | None = None,
    available_tools: list[str] | None = None,
) -> WorkflowExecutor:
    """Create a WorkflowExecutor with mocked dependencies."""
    availability = MagicMock()
    availability.get_mcp_manager.return_value = mcp_manager
    if available_tools is not None:
        availability.is_tool_available.side_effect = lambda t: t in available_tools
    else:
        availability.is_tool_available.return_value = True

    tool_proxy = MagicMock()
    return WorkflowExecutor(
        availability_reporter=availability,
        tool_proxy=tool_proxy,
    )


def _mock_mcp_manager(content: str = "ok", error: str | None = None) -> MagicMock:
    """Create a mock MCPClientManager that returns a canned result."""
    result = MagicMock()
    result.content = content
    result.error = error

    manager = MagicMock()
    manager.call_tool = AsyncMock(return_value=result)
    return manager


# ---------------------------------------------------------------------------
# BUG-001 regression: "arguments" key must be used, not "args"
# ---------------------------------------------------------------------------


@pytest.mark.runner_unit
class TestHandleToolCallArguments:
    """BUG-001 regression: verify arguments are forwarded correctly."""

    @pytest.mark.asyncio
    async def test_arguments_key_forwarded_to_mcp(self):
        """CP sends 'arguments'; executor must read that key and forward it."""
        manager = _mock_mcp_manager()
        executor = _make_executor(mcp_manager=manager, available_tools=["fs__read_file"])

        params = {
            "tool": "fs__read_file",
            "arguments": {"path": "/home/user/file.txt"},
        }

        result = await executor.handle_tool_call(params)

        assert result["status"] == "success"
        manager.call_tool.assert_called_once_with(
            server_name="fs",
            tool_name="read_file",
            arguments={"path": "/home/user/file.txt"},
        )

    @pytest.mark.asyncio
    async def test_arguments_not_silently_dropped(self):
        """Ensure arguments dict is not replaced by empty default."""
        manager = _mock_mcp_manager()
        executor = _make_executor(mcp_manager=manager, available_tools=["obsidian__entity"])

        params = {
            "tool": "obsidian__entity",
            "arguments": {"action": "get", "id": "M-031", "fields": ["status"]},
        }

        await executor.handle_tool_call(params)

        _, kwargs = manager.call_tool.call_args
        assert kwargs["arguments"] == {
            "action": "get",
            "id": "M-031",
            "fields": ["status"],
        }

    @pytest.mark.asyncio
    async def test_empty_arguments_still_works(self):
        """Zero-param tool calls should still succeed (empty dict)."""
        manager = _mock_mcp_manager()
        executor = _make_executor(mcp_manager=manager, available_tools=["obsidian__rebuild_index"])

        result = await executor.handle_tool_call(
            {"tool": "obsidian__rebuild_index", "arguments": {}}
        )

        assert result["status"] == "success"
        manager.call_tool.assert_called_once_with(
            server_name="obsidian", tool_name="rebuild_index", arguments={}
        )

    @pytest.mark.asyncio
    async def test_missing_arguments_key_defaults_to_empty(self):
        """If CP omits 'arguments' entirely, default to empty dict."""
        manager = _mock_mcp_manager()
        executor = _make_executor(mcp_manager=manager, available_tools=["obsidian__rebuild_index"])

        result = await executor.handle_tool_call({"tool": "obsidian__rebuild_index"})

        assert result["status"] == "success"
        manager.call_tool.assert_called_once_with(
            server_name="obsidian", tool_name="rebuild_index", arguments={}
        )

    @pytest.mark.asyncio
    async def test_old_args_key_is_not_used(self):
        """Ensure the old buggy 'args' key is NOT read (regression guard)."""
        manager = _mock_mcp_manager()
        executor = _make_executor(mcp_manager=manager, available_tools=["fs__read_file"])

        # Simulate a message that has ONLY the old "args" key
        params = {"tool": "fs__read_file", "args": {"path": "/should/not/be/read"}}

        await executor.handle_tool_call(params)

        # arguments should be empty — the "args" key must be ignored
        _, kwargs = manager.call_tool.call_args
        assert kwargs["arguments"] == {}


# ---------------------------------------------------------------------------
# Contract tests: tool name parsing and error paths
# ---------------------------------------------------------------------------


@pytest.mark.runner_unit
class TestHandleToolCallEdgeCases:
    """Additional edge-case tests for handle_tool_call."""

    @pytest.mark.asyncio
    async def test_missing_tool_name_returns_error(self):
        """Missing tool name should return INVALID_PARAMS error."""
        manager = _mock_mcp_manager()
        executor = _make_executor(mcp_manager=manager)

        result = await executor.handle_tool_call({"arguments": {"x": 1}})

        assert result["status"] == "error"
        assert result["error"]["code"] == "INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_invalid_tool_name_format_returns_error(self):
        """Tool name without __ separator should return error."""
        manager = _mock_mcp_manager()
        executor = _make_executor(mcp_manager=manager, available_tools=["badtoolname"])

        result = await executor.handle_tool_call({"tool": "badtoolname", "arguments": {"x": 1}})

        assert result["status"] == "error"
        assert result["error"]["code"] == "INVALID_TOOL_NAME"

    @pytest.mark.asyncio
    async def test_unavailable_tool_returns_error(self):
        """Calling an unavailable tool should return TOOL_UNAVAILABLE."""
        manager = _mock_mcp_manager()
        executor = _make_executor(mcp_manager=manager, available_tools=[])

        result = await executor.handle_tool_call(
            {"tool": "fs__read_file", "arguments": {"path": "/tmp"}}
        )

        assert result["status"] == "error"
        assert result["error"]["code"] == "TOOL_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_mcp_manager_not_initialized_returns_error(self):
        """If MCP manager is None, should return EXECUTOR_NOT_INITIALIZED."""
        executor = _make_executor(mcp_manager=None)

        result = await executor.handle_tool_call(
            {"tool": "fs__read_file", "arguments": {"path": "/tmp"}}
        )

        assert result["status"] == "error"
        assert result["error"]["code"] == "EXECUTOR_NOT_INITIALIZED"

    @pytest.mark.asyncio
    async def test_complex_nested_arguments_forwarded(self):
        """Complex nested arguments should be forwarded intact."""
        manager = _mock_mcp_manager()
        executor = _make_executor(mcp_manager=manager, available_tools=["obsidian__entity"])

        complex_args = {
            "action": "update",
            "id": "T-700",
            "fields": {
                "status": "done",
                "tags": ["sprint-42", "infra"],
                "metadata": {"priority": 1, "nested": {"deep": True}},
            },
        }

        await executor.handle_tool_call({"tool": "obsidian__entity", "arguments": complex_args})

        _, kwargs = manager.call_tool.call_args
        assert kwargs["arguments"] == complex_args

    @pytest.mark.asyncio
    async def test_tool_call_exception_returns_error(self):
        """If MCP call_tool raises, should return TOOL_FAILED error."""
        manager = MagicMock()
        manager.call_tool = AsyncMock(side_effect=RuntimeError("connection lost"))
        executor = _make_executor(mcp_manager=manager, available_tools=["fs__read_file"])

        result = await executor.handle_tool_call(
            {"tool": "fs__read_file", "arguments": {"path": "/tmp"}}
        )

        assert result["status"] == "error"
        assert result["error"]["code"] == "TOOL_FAILED"
        assert "connection lost" in result["error"]["message"]
