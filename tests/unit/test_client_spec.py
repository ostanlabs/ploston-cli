"""Specification tests for ploston_cli.client.PlostClient.

These tests assert the *intended* behavior of the HTTP client per its
docstrings/contract: correct HTTP method, path, body, query params, response
parsing, and error mapping. External boundary (httpx transport) is faked with
``httpx.MockTransport`` so the unit under test (PlostClient._request and the
public methods) runs for real.

Tests are spec-driven: they assert correct/intended behavior, not whatever the
code happens to currently produce.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ploston_cli.client import (
    CPConnectionResult,
    PlostClient,
    PlostClientError,
)

BASE_URL = "http://cp.example:8022"


def _make_client(handler, *, base_url: str = BASE_URL, **kwargs) -> PlostClient:
    """Build a PlostClient whose underlying httpx client uses a MockTransport.

    ``handler`` is a callable ``(httpx.Request) -> httpx.Response``.
    The recorded requests are stored on ``client.recorded`` for assertions.
    """
    client = PlostClient(base_url, **kwargs)
    recorded: list[httpx.Request] = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler(request)

    transport = httpx.MockTransport(_wrapped)
    # Mirror __aenter__ but inject the mock transport at the boundary only.
    client._client = httpx.AsyncClient(
        base_url=client.base_url,
        timeout=client.timeout,
        headers={"Content-Type": "application/json"},
        transport=transport,
    )
    client.recorded = recorded  # type: ignore[attr-defined]
    return client


async def _aclose(client: PlostClient) -> None:
    if client._client is not None:
        await client._client.aclose()
        client._client = None


# ---------------------------------------------------------------------------
# Construction / base_url normalization
# ---------------------------------------------------------------------------


def test_base_url_trailing_slash_stripped():
    """base_url should be normalized by stripping a trailing slash (docstring)."""
    c = PlostClient("http://localhost:8022/")
    assert c.base_url == "http://localhost:8022"


def test_default_timeout_is_30s():
    c = PlostClient("http://localhost:8022")
    assert c.timeout == 30.0


def test_ensure_client_raises_when_not_in_context():
    """Calling a method outside the async context must raise a clear error."""
    c = PlostClient("http://localhost:8022")
    with pytest.raises(PlostClientError) as ei:
        c._ensure_client()
    assert "context" in str(ei.value).lower()


# ---------------------------------------------------------------------------
# Method / path / params / body correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_capabilities_uses_correct_endpoint():
    payload = {"tier": "oss", "version": "1.2.3", "features": [], "limits": {}}
    client = _make_client(lambda r: httpx.Response(200, json=payload))
    try:
        result = await client.get_capabilities()
    finally:
        await _aclose(client)

    assert result == payload
    req = client.recorded[-1]  # type: ignore[attr-defined]
    assert req.method == "GET"
    assert req.url.path == "/api/v1/capabilities"


@pytest.mark.asyncio
async def test_list_workflows_unwraps_workflows_key():
    """list_workflows must return only the inner list, not the envelope."""
    payload = {"workflows": [{"name": "wf1"}, {"name": "wf2"}], "total": 2}
    client = _make_client(lambda r: httpx.Response(200, json=payload))
    try:
        result = await client.list_workflows()
    finally:
        await _aclose(client)
    assert result == [{"name": "wf1"}, {"name": "wf2"}]


@pytest.mark.asyncio
async def test_list_workflows_missing_key_returns_empty_list():
    """If the envelope lacks 'workflows', the contract returns []."""
    client = _make_client(lambda r: httpx.Response(200, json={"total": 0}))
    try:
        result = await client.list_workflows()
    finally:
        await _aclose(client)
    assert result == []


@pytest.mark.asyncio
async def test_get_workflow_url_encodes_name_in_path():
    client = _make_client(lambda r: httpx.Response(200, json={"name": "my-wf"}))
    try:
        await client.get_workflow("my-wf")
    finally:
        await _aclose(client)
    req = client.recorded[-1]  # type: ignore[attr-defined]
    assert req.method == "GET"
    assert req.url.path == "/api/v1/workflows/my-wf"


@pytest.mark.asyncio
async def test_execute_workflow_posts_inputs_and_timeout():
    captured: dict[str, Any] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(r.content)
        return httpx.Response(200, json={"status": "completed"})

    client = _make_client(handler)
    try:
        await client.execute_workflow("wf", inputs={"a": 1}, timeout=42)
    finally:
        await _aclose(client)

    req = client.recorded[-1]  # type: ignore[attr-defined]
    assert req.method == "POST"
    assert req.url.path == "/api/v1/workflows/wf/execute"
    assert captured["body"] == {"inputs": {"a": 1}, "timeout": 42}


@pytest.mark.asyncio
async def test_execute_workflow_defaults_inputs_to_empty_and_omits_timeout():
    captured: dict[str, Any] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(r.content)
        return httpx.Response(200, json={})

    client = _make_client(handler)
    try:
        await client.execute_workflow("wf")
    finally:
        await _aclose(client)

    assert captured["body"] == {"inputs": {}}
    assert "timeout" not in captured["body"]


@pytest.mark.asyncio
async def test_list_tools_sends_only_provided_filters_as_query_params():
    client = _make_client(lambda r: httpx.Response(200, json={"tools": []}))
    try:
        await client.list_tools(source="mcp", status="available")
    finally:
        await _aclose(client)
    req = client.recorded[-1]  # type: ignore[attr-defined]
    params = dict(req.url.params)
    assert params == {"source": "mcp", "status": "available"}
    assert "server" not in params


@pytest.mark.asyncio
async def test_list_tools_no_filters_sends_no_query_params():
    client = _make_client(lambda r: httpx.Response(200, json={"tools": [{"name": "t"}]}))
    try:
        result = await client.list_tools()
    finally:
        await _aclose(client)
    req = client.recorded[-1]  # type: ignore[attr-defined]
    assert str(req.url.query, "utf-8") == ""
    assert result == [{"name": "t"}]


@pytest.mark.asyncio
async def test_refresh_tools_posts_to_refresh_endpoint_with_server_param():
    client = _make_client(lambda r: httpx.Response(200, json={"refreshed": 1}))
    try:
        await client.refresh_tools(server="github")
    finally:
        await _aclose(client)
    req = client.recorded[-1]  # type: ignore[attr-defined]
    assert req.method == "POST"
    assert req.url.path == "/api/v1/tools/refresh"
    assert dict(req.url.params) == {"server": "github"}


@pytest.mark.asyncio
async def test_list_executions_maps_workflow_to_workflow_id_and_includes_paging():
    client = _make_client(lambda r: httpx.Response(200, json={"executions": []}))
    try:
        await client.list_executions(workflow="wf", status="completed", page=2, page_size=5)
    finally:
        await _aclose(client)
    req = client.recorded[-1]  # type: ignore[attr-defined]
    params = dict(req.url.params)
    assert params["workflow_id"] == "wf"
    assert params["status"] == "completed"
    assert params["page"] == "2"
    assert params["page_size"] == "5"


@pytest.mark.asyncio
async def test_create_runner_posts_name_and_mcps():
    captured: dict[str, Any] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(r.content)
        return httpx.Response(200, json={"name": "r1", "token": "tok"})

    client = _make_client(handler)
    try:
        await client.create_runner("r1", mcps={"github": {"command": "x"}})
    finally:
        await _aclose(client)
    req = client.recorded[-1]  # type: ignore[attr-defined]
    assert req.method == "POST"
    assert req.url.path == "/api/v1/runners"
    assert captured["body"] == {"name": "r1", "mcps": {"github": {"command": "x"}}}


@pytest.mark.asyncio
async def test_delete_runner_uses_delete_method():
    client = _make_client(lambda r: httpx.Response(200, json={"deleted": True}))
    try:
        await client.delete_runner("r1")
    finally:
        await _aclose(client)
    req = client.recorded[-1]  # type: ignore[attr-defined]
    assert req.method == "DELETE"
    assert req.url.path == "/api/v1/runners/r1"


@pytest.mark.asyncio
async def test_get_runner_token_returns_token_string():
    client = _make_client(lambda r: httpx.Response(200, json={"token": "secret-tok"}))
    try:
        token = await client.get_runner_token("r1")
    finally:
        await _aclose(client)
    assert token == "secret-tok"
    req = client.recorded[-1]  # type: ignore[attr-defined]
    assert req.url.path == "/api/v1/runners/r1/token"


@pytest.mark.asyncio
async def test_enter_configuration_mode_posts_mode_payload():
    captured: dict[str, Any] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(r.content)
        return httpx.Response(200, json={"mode": "configuration"})

    client = _make_client(handler)
    try:
        await client.enter_configuration_mode()
    finally:
        await _aclose(client)
    assert captured["body"] == {"mode": "configuration"}


@pytest.mark.asyncio
async def test_config_set_posts_path_and_value():
    captured: dict[str, Any] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(r.content)
        return httpx.Response(200, json={"staged": True})

    client = _make_client(handler)
    try:
        await client.config_set("runners.local", {"token": "t"})
    finally:
        await _aclose(client)
    assert captured["body"] == {"path": "runners.local", "value": {"token": "t"}}


# ---------------------------------------------------------------------------
# push_runner_config — multi-call orchestration & merge contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_runner_config_enters_config_mode_when_not_already():
    paths_seen: list[tuple[str, str]] = []

    def handler(r: httpx.Request) -> httpx.Response:
        paths_seen.append((r.method, r.url.path))
        if r.url.path == "/api/v1/config/mode" and r.method == "GET":
            return httpx.Response(200, json={"mode": "execution"})
        if r.url.path == "/api/v1/config/mode" and r.method == "POST":
            return httpx.Response(200, json={"mode": "configuration"})
        if r.url.path == "/api/v1/config/set":
            return httpx.Response(200, json={"staged": True})
        if r.url.path == "/api/v1/config/done":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404, json={"detail": "nope"})

    client = _make_client(handler)
    try:
        result = await client.push_runner_config("local", {"github": {"command": "x"}}, token="tok")
    finally:
        await _aclose(client)

    assert result == {"success": True}
    # Must check mode (GET), enter config mode (POST), set, then done.
    assert ("GET", "/api/v1/config/mode") in paths_seen
    assert ("POST", "/api/v1/config/mode") in paths_seen
    assert ("POST", "/api/v1/config/set") in paths_seen
    assert ("POST", "/api/v1/config/done") in paths_seen


@pytest.mark.asyncio
async def test_push_runner_config_skips_enter_mode_when_already_configuration():
    enter_calls = {"count": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path == "/api/v1/config/mode" and r.method == "GET":
            return httpx.Response(200, json={"mode": "configuration"})
        if r.url.path == "/api/v1/config/mode" and r.method == "POST":
            enter_calls["count"] += 1
            return httpx.Response(200, json={"mode": "configuration"})
        if r.url.path == "/api/v1/config/set":
            return httpx.Response(200, json={"staged": True})
        if r.url.path == "/api/v1/config/done":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404, json={"detail": "nope"})

    client = _make_client(handler)
    try:
        await client.push_runner_config("local", {"a": {}}, token="t")
    finally:
        await _aclose(client)

    assert enter_calls["count"] == 0, "should not re-enter configuration mode"


@pytest.mark.asyncio
async def test_push_runner_config_merge_combines_existing_and_new_servers():
    captured_set: dict[str, Any] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        import json as _json

        if r.url.path == "/api/v1/config/mode" and r.method == "GET":
            return httpx.Response(200, json={"mode": "configuration"})
        if r.url.path == "/api/v1/config/runners/local":
            return httpx.Response(200, json={"mcp_servers": {"old": {"command": "o"}}})
        if r.url.path == "/api/v1/config/set":
            captured_set.update(_json.loads(r.content))
            return httpx.Response(200, json={"staged": True})
        if r.url.path == "/api/v1/config/done":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404, json={"detail": "nope"})

    client = _make_client(handler)
    try:
        await client.push_runner_config("local", {"new": {"command": "n"}}, token="t", merge=True)
    finally:
        await _aclose(client)

    servers = captured_set["value"]["mcp_servers"]
    assert servers == {"old": {"command": "o"}, "new": {"command": "n"}}


@pytest.mark.asyncio
async def test_push_runner_config_merge_tolerates_missing_existing_runner():
    """When the runner doesn't exist (404 on GET), merge falls back to creation."""
    captured_set: dict[str, Any] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        import json as _json

        if r.url.path == "/api/v1/config/mode" and r.method == "GET":
            return httpx.Response(200, json={"mode": "configuration"})
        if r.url.path == "/api/v1/config/runners/local":
            return httpx.Response(404, json={"detail": "not found"})
        if r.url.path == "/api/v1/config/set":
            captured_set.update(_json.loads(r.content))
            return httpx.Response(200, json={"staged": True})
        if r.url.path == "/api/v1/config/done":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404, json={"detail": "nope"})

    client = _make_client(handler)
    try:
        await client.push_runner_config("local", {"new": {"command": "n"}}, token="t", merge=True)
    finally:
        await _aclose(client)

    assert captured_set["value"]["mcp_servers"] == {"new": {"command": "n"}}


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_error_extracts_detail_field_and_status_code():
    client = _make_client(lambda r: httpx.Response(404, json={"detail": "workflow not found"}))
    try:
        with pytest.raises(PlostClientError) as ei:
            await client.get_workflow("missing")
    finally:
        await _aclose(client)
    assert ei.value.message == "workflow not found"
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_http_error_without_json_detail_still_maps_status_code():
    client = _make_client(lambda r: httpx.Response(500, text="boom"))
    try:
        with pytest.raises(PlostClientError) as ei:
            await client.get_capabilities()
    finally:
        await _aclose(client)
    assert ei.value.status_code == 500


@pytest.mark.asyncio
async def test_connect_error_maps_to_friendly_message():
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=r)

    client = _make_client(handler)
    try:
        with pytest.raises(PlostClientError) as ei:
            await client.health()
    finally:
        await _aclose(client)
    msg = str(ei.value)
    assert "Cannot connect" in msg
    assert BASE_URL in msg


@pytest.mark.asyncio
async def test_timeout_error_maps_to_timeout_message():
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=r)

    client = _make_client(handler, timeout=7.5)
    try:
        with pytest.raises(PlostClientError) as ei:
            await client.health()
    finally:
        await _aclose(client)
    assert "timed out" in str(ei.value).lower()
    assert "7.5" in str(ei.value)


@pytest.mark.asyncio
async def test_read_error_maps_to_interrupted_message():
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("read failed", request=r)

    client = _make_client(handler)
    try:
        with pytest.raises(PlostClientError) as ei:
            await client.health()
    finally:
        await _aclose(client)
    assert "interrupted" in str(ei.value).lower()


# ---------------------------------------------------------------------------
# check_cp_connectivity wraps health()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_cp_connectivity_success_returns_connected_result():
    client = _make_client(lambda r: httpx.Response(200, json={"version": "9.9.9"}))
    try:
        result = await client.check_cp_connectivity()
    finally:
        await _aclose(client)
    assert isinstance(result, CPConnectionResult)
    assert result.connected is True
    assert result.version == "9.9.9"
    assert result.url == BASE_URL
    assert result.error is None


@pytest.mark.asyncio
async def test_check_cp_connectivity_failure_returns_disconnected_result():
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=r)

    client = _make_client(handler)
    try:
        result = await client.check_cp_connectivity()
    finally:
        await _aclose(client)
    assert result.connected is False
    assert result.error is not None
    assert result.version is None


# ---------------------------------------------------------------------------
# Remaining endpoint coverage (method/path correctness)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_runners_unwraps_runners_key_and_passes_status_filter():
    client = _make_client(lambda r: httpx.Response(200, json={"runners": [{"name": "r"}]}))
    try:
        result = await client.list_runners(status="connected")
    finally:
        await _aclose(client)
    assert result == [{"name": "r"}]
    req = client.recorded[-1]  # type: ignore[attr-defined]
    assert req.url.path == "/api/v1/runners"
    assert dict(req.url.params) == {"status": "connected"}


@pytest.mark.asyncio
async def test_get_runner_uses_correct_path():
    client = _make_client(lambda r: httpx.Response(200, json={"name": "r"}))
    try:
        await client.get_runner("r")
    finally:
        await _aclose(client)
    assert client.recorded[-1].url.path == "/api/v1/runners/r"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_regenerate_runner_token_posts_to_regenerate_endpoint():
    client = _make_client(lambda r: httpx.Response(200, json={"token": "new"}))
    try:
        await client.regenerate_runner_token("r")
    finally:
        await _aclose(client)
    req = client.recorded[-1]  # type: ignore[attr-defined]
    assert req.method == "POST"
    assert req.url.path == "/api/v1/runners/r/regenerate-token"


@pytest.mark.asyncio
async def test_get_config_passes_section_param():
    client = _make_client(lambda r: httpx.Response(200, json={}))
    try:
        await client.get_config(section="runners")
    finally:
        await _aclose(client)
    req = client.recorded[-1]  # type: ignore[attr-defined]
    assert req.url.path == "/api/v1/config"
    assert dict(req.url.params) == {"section": "runners"}


@pytest.mark.asyncio
async def test_get_config_diff_and_mode_and_done_endpoints():
    routes = {
        "/api/v1/config/diff": {"has_changes": False},
        "/api/v1/config/mode": {"mode": "execution"},
        "/api/v1/config/done": {"success": True},
    }
    client = _make_client(lambda r: httpx.Response(200, json=routes[r.url.path]))
    try:
        assert (await client.get_config_diff()) == {"has_changes": False}
        assert (await client.get_mode()) == {"mode": "execution"}
        assert (await client.config_done()) == {"success": True}
    finally:
        await _aclose(client)


@pytest.mark.asyncio
async def test_get_execution_uses_execution_id_in_path():
    client = _make_client(lambda r: httpx.Response(200, json={"id": "e1"}))
    try:
        await client.get_execution("e1")
    finally:
        await _aclose(client)
    assert client.recorded[-1].url.path == "/api/v1/executions/e1"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_get_tool_uses_tool_name_in_path():
    client = _make_client(lambda r: httpx.Response(200, json={"name": "t"}))
    try:
        await client.get_tool("t")
    finally:
        await _aclose(client)
    assert client.recorded[-1].url.path == "/api/v1/tools/t"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_context_manager_creates_and_closes_real_client():
    """__aenter__/__aexit__ must manage the lifecycle of the httpx client."""
    c = PlostClient(BASE_URL)
    assert c._client is None
    async with c as entered:
        assert entered is c
        assert c._client is not None
    assert c._client is None
