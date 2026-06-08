"""Specification tests for ploston_cli.runner.health_server.

Covers HealthStatus derivations (status / uptime / to_dict) and the HealthServer
request handling (GET /health -> 200 JSON; anything else -> 404), driven over a
real localhost socket. The socket is the external boundary; the request-parsing
and response-building logic under test runs for real.

We bind the server to an ephemeral port (monkeypatching the module constant) so
tests never collide with a real runner on 9876.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import ploston_cli.runner.health_server as hs_mod
from ploston_cli.runner.health_server import HealthServer, HealthStatus

# ---------------------------------------------------------------------------
# HealthStatus pure logic
# ---------------------------------------------------------------------------


def test_status_unhealthy_when_cp_disconnected():
    status = HealthStatus(cp_connected=False)
    assert status.status == "unhealthy"


def test_status_degraded_when_connected_but_tools_unavailable():
    status = HealthStatus(cp_connected=True, unavailable_tools=2)
    assert status.status == "degraded"


def test_status_healthy_when_connected_and_all_tools_available():
    status = HealthStatus(cp_connected=True, unavailable_tools=0)
    assert status.status == "healthy"


def test_uptime_is_nonnegative_int(monkeypatch):
    # start_time 10s in the past -> uptime ~10
    monkeypatch.setattr(hs_mod.time, "time", lambda: 1000.0)
    status = HealthStatus(start_time=990.0)
    assert status.uptime_seconds == 10
    assert isinstance(status.uptime_seconds, int)


def test_to_dict_includes_all_contract_fields():
    status = HealthStatus(
        name="runner-1",
        cp_connected=True,
        cp_url="ws://cp",
        available_tools=3,
        unavailable_tools=0,
        tools={"github__search": "available"},
        last_config_received="2026-01-01T00:00:00Z",
        version="2.0.0",
    )
    d = status.to_dict()
    assert d["status"] == "healthy"
    assert d["name"] == "runner-1"
    assert d["cp_connected"] is True
    assert d["cp_url"] == "ws://cp"
    assert d["available_tools"] == 3
    assert d["unavailable_tools"] == 0
    assert d["tools"] == {"github__search": "available"}
    assert d["last_config_received"] == "2026-01-01T00:00:00Z"
    assert d["version"] == "2.0.0"
    assert "uptime_seconds" in d


# ---------------------------------------------------------------------------
# HealthServer over a real localhost socket
# ---------------------------------------------------------------------------


async def _start_server_on_free_port(monkeypatch, health_status):
    """Start a HealthServer on an OS-assigned free port; return (server, port)."""
    monkeypatch.setattr(hs_mod, "HEALTH_PORT", 0)  # let OS choose
    server = HealthServer(health_status)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    return server, port


async def _raw_request(port: int, request: str) -> str:
    reader, writer = await asyncio.open_connection(hs_mod.HEALTH_HOST, port)
    writer.write(request.encode("utf-8"))
    await writer.drain()
    data = await asyncio.wait_for(reader.read(-1), timeout=5.0)
    writer.close()
    await writer.wait_closed()
    return data.decode("utf-8")


def _split_response(raw: str) -> tuple[str, dict]:
    head, _, body = raw.partition("\r\n\r\n")
    status_line = head.splitlines()[0]
    return status_line, json.loads(body)


async def test_get_health_returns_200_with_status_json(monkeypatch):
    health_status = HealthStatus(name="r1", cp_connected=True, available_tools=2)
    server, port = await _start_server_on_free_port(monkeypatch, health_status)
    try:
        raw = await _raw_request(port, "GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
    finally:
        await server.stop()

    status_line, body = _split_response(raw)
    assert "200" in status_line
    assert body["name"] == "r1"
    assert body["status"] == "healthy"
    assert body["available_tools"] == 2


async def test_unknown_path_returns_404(monkeypatch):
    server, port = await _start_server_on_free_port(monkeypatch, HealthStatus())
    try:
        raw = await _raw_request(port, "GET /not-here HTTP/1.1\r\nHost: x\r\n\r\n")
    finally:
        await server.stop()

    status_line, body = _split_response(raw)
    assert "404" in status_line
    assert body == {"error": "Not Found"}


async def test_non_get_method_on_health_returns_404(monkeypatch):
    """Health endpoint is GET-only; POST /health must be rejected (404)."""
    server, port = await _start_server_on_free_port(monkeypatch, HealthStatus())
    try:
        raw = await _raw_request(port, "POST /health HTTP/1.1\r\nHost: x\r\n\r\n")
    finally:
        await server.stop()

    status_line, _ = _split_response(raw)
    assert "404" in status_line


async def test_response_has_json_content_type_and_correct_length(monkeypatch):
    server, port = await _start_server_on_free_port(monkeypatch, HealthStatus())
    try:
        raw = await _raw_request(port, "GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
    finally:
        await server.stop()

    head, _, body = raw.partition("\r\n\r\n")
    assert "Content-Type: application/json" in head
    # Content-Length header must match actual body byte length.
    cl_line = next(line for line in head.splitlines() if line.lower().startswith("content-length"))
    declared = int(cl_line.split(":")[1].strip())
    assert declared == len(body.encode("utf-8"))


async def test_stop_releases_the_port_so_it_can_be_rebound(monkeypatch):
    server, port = await _start_server_on_free_port(monkeypatch, HealthStatus())
    await server.stop()
    assert server._server is None
    # After stop, connecting should fail (server no longer listening).
    with pytest.raises((ConnectionRefusedError, OSError)):
        reader, writer = await asyncio.open_connection(hs_mod.HEALTH_HOST, port)
        writer.close()
        await writer.wait_closed()
