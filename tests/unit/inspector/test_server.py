"""Tests for the inspector Starlette app routes (without spinning up a server)."""

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from ploston_cli.inspector.proxy import InspectorProxyError
from ploston_cli.inspector.server import create_app


def _mk_proxy():
    proxy = AsyncMock()
    proxy.url = "http://cp:8022"
    proxy.get_capabilities.return_value = {"version": "1.0"}
    proxy.health.return_value = {"status": "ok"}
    proxy.get_config.return_value = {"tools": {"mcp_servers": {}}}
    proxy.list_runners.return_value = []
    proxy.list_tools.return_value = []
    proxy.get_runner.return_value = {"mcps": []}
    proxy.get_cp_mcp_status.return_value = {"status": "connected", "tool_count": 0}
    proxy.get_runner_mcp_status.return_value = {"status": "connected"}
    proxy.refresh_tools.return_value = {"refreshed": 0, "servers": {}}
    return proxy


@pytest.fixture
def client():
    """Client with EventHub background tasks patched out so we don't subscribe to CP."""
    proxy = _mk_proxy()
    with (
        patch("ploston_cli.inspector.server.EventHub.start", new=AsyncMock()),
        patch("ploston_cli.inspector.server.EventHub.stop", new=AsyncMock()),
    ):
        app = create_app(proxy)
        app.state.test_proxy = proxy
        with TestClient(app) as c:
            yield c, proxy


def test_healthz(client):
    c, _ = client
    response = c.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_api_overview(client):
    c, _ = client
    response = c.get("/api/overview")
    assert response.status_code == 200
    payload = response.json()
    assert "cp" in payload
    assert "servers" in payload
    assert "tools" in payload


def test_api_refresh_cp_scoped(client):
    c, proxy = client
    response = c.post("/api/refresh", params={"server_id": "cp::filesystem"})
    assert response.status_code == 200
    proxy.refresh_tools.assert_awaited_with(server="filesystem")


def test_api_refresh_global(client):
    c, proxy = client
    response = c.post("/api/refresh")
    assert response.status_code == 200
    proxy.refresh_tools.assert_awaited_with()


def test_api_refresh_runner_server_deferred(client):
    c, _ = client
    response = c.post("/api/refresh", params={"server_id": "runner:host-a::slack"})
    assert response.status_code == 501
    assert "deferred" in response.json()["error"].lower()


def test_api_refresh_native_rejected(client):
    c, _ = client
    response = c.post("/api/refresh", params={"server_id": "native::clock"})
    assert response.status_code == 400


def test_api_server_status_cp(client):
    c, proxy = client
    response = c.get("/api/server/status", params={"server_id": "cp::filesystem"})
    assert response.status_code == 200
    proxy.get_cp_mcp_status.assert_awaited_with("filesystem")


def test_api_server_status_runner(client):
    c, proxy = client
    response = c.get("/api/server/status", params={"server_id": "runner:host-a::slack"})
    assert response.status_code == 200
    proxy.get_runner_mcp_status.assert_awaited_with("host-a", "slack")


def test_api_server_status_missing_id(client):
    c, _ = client
    response = c.get("/api/server/status")
    assert response.status_code == 400


def test_api_server_status_unknown_kind(client):
    c, _ = client
    response = c.get("/api/server/status", params={"server_id": "quantum::foo"})
    assert response.status_code == 400


def test_api_overview_propagates_proxy_error(client):
    c, proxy = client
    proxy.get_capabilities.side_effect = InspectorProxyError("network down")
    proxy.health.side_effect = InspectorProxyError("network down")
    proxy.get_config.side_effect = InspectorProxyError("network down")
    proxy.list_runners.side_effect = InspectorProxyError("network down")
    proxy.list_tools.side_effect = InspectorProxyError("network down")
    # With all stages failing, overview still renders (safe degradation) with 200
    response = c.get("/api/overview")
    assert response.status_code == 200
    assert response.json()["cp"]["connected"] is False


def test_root_serves_spa_index_html(client):
    c, _ = client
    response = c.get("/")
    assert response.status_code == 200
    assert "Ploston Inspector" in response.text


def test_static_mount_exists(client):
    c, _ = client
    # Mount is served; a known file would 200 — missing assets 404. Just verify
    # the route is registered by asking for a non-existent file (should 404, not 500).
    response = c.get("/static/does-not-exist.css")
    assert response.status_code == 404
