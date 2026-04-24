"""Unit tests for InspectorProxy REST surface."""

from unittest.mock import AsyncMock

import httpx
import pytest

from ploston_cli.inspector.proxy import InspectorProxy, InspectorProxyError


@pytest.fixture
def proxy():
    return InspectorProxy(url="http://localhost:8022", token="test-token")


def test_invalid_url_raises():
    with pytest.raises(ValueError):
        InspectorProxy(url="not-a-url")


def test_headers_include_auth(proxy):
    headers = proxy._headers()
    assert headers["Authorization"] == "Bearer test-token"
    assert headers["Content-Type"] == "application/json"


def test_headers_without_token():
    p = InspectorProxy(url="http://localhost:8022")
    headers = p._headers()
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_health_calls_correct_path(proxy):
    mock_client = AsyncMock()
    mock_client.get.return_value = httpx.Response(200, json={"status": "ok"})
    proxy._client = mock_client

    result = await proxy.health()
    assert result == {"status": "ok"}
    mock_client.get.assert_called_once_with("http://localhost:8022/health", params=None)


@pytest.mark.asyncio
async def test_list_runners_unwraps_dict(proxy):
    mock_client = AsyncMock()
    mock_client.get.return_value = httpx.Response(
        200, json={"runners": [{"name": "r1"}, {"name": "r2"}]}
    )
    proxy._client = mock_client

    result = await proxy.list_runners()
    assert result == [{"name": "r1"}, {"name": "r2"}]


@pytest.mark.asyncio
async def test_list_tools_unwraps_dict(proxy):
    mock_client = AsyncMock()
    mock_client.get.return_value = httpx.Response(200, json={"tools": [{"name": "t1"}]})
    proxy._client = mock_client

    result = await proxy.list_tools()
    assert result == [{"name": "t1"}]


@pytest.mark.asyncio
async def test_refresh_tools_with_server_sends_query_param(proxy):
    mock_client = AsyncMock()
    mock_client.post.return_value = httpx.Response(200, json={"refreshed": 1})
    proxy._client = mock_client

    await proxy.refresh_tools(server="filesystem")
    args, kwargs = mock_client.post.call_args
    assert kwargs["params"] == {"server": "filesystem"}


@pytest.mark.asyncio
async def test_refresh_tools_without_server_sends_none(proxy):
    mock_client = AsyncMock()
    mock_client.post.return_value = httpx.Response(200, json={"refreshed": 5})
    proxy._client = mock_client

    await proxy.refresh_tools()
    args, kwargs = mock_client.post.call_args
    assert kwargs["params"] is None


@pytest.mark.asyncio
async def test_get_cp_mcp_status_path(proxy):
    mock_client = AsyncMock()
    mock_client.get.return_value = httpx.Response(200, json={"status": "connected"})
    proxy._client = mock_client

    await proxy.get_cp_mcp_status("filesystem")
    args, kwargs = mock_client.get.call_args
    assert args[0] == "http://localhost:8022/api/v1/mcp-servers/filesystem/status"


@pytest.mark.asyncio
async def test_http_error_maps_to_inspector_error(proxy):
    mock_client = AsyncMock()
    mock_client.get.return_value = httpx.Response(500, text="server error")
    proxy._client = mock_client

    with pytest.raises(InspectorProxyError) as excinfo:
        await proxy.health()
    assert "HTTP 500" in str(excinfo.value)


@pytest.mark.asyncio
async def test_connection_error_maps_to_inspector_error(proxy):
    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.ConnectError("refused")
    proxy._client = mock_client

    with pytest.raises(InspectorProxyError) as excinfo:
        await proxy.health()
    assert "Connection error" in str(excinfo.value)


@pytest.mark.asyncio
async def test_close_marks_closed_and_prevents_reuse(proxy):
    mock_client = AsyncMock()
    proxy._client = mock_client

    await proxy.close()
    assert proxy._closed is True

    with pytest.raises(InspectorProxyError):
        await proxy._ensure_client()
