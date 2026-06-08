"""CR-2 (runner side): TLS handling in RunnerConnection.

- wss:// to a non-localhost CP must pass an ssl context to websockets.connect.
- ws:// (or wss to localhost) must NOT pass ssl (plaintext dev path, DEC-118).
"""

import ssl
from unittest.mock import AsyncMock, patch

import pytest
import websockets

from ploston_cli.runner.connection import RunnerConnection
from ploston_cli.runner.types import RunnerConfig


def _conn(url: str, ssl_context=None) -> RunnerConnection:
    cfg = RunnerConfig(
        control_plane_url=url,
        auth_token="t",
        runner_name="r",
        ssl_context=ssl_context,
    )
    return RunnerConnection(config=cfg)


@pytest.mark.runner_unit
class TestConnectKwargs:
    def test_plaintext_localhost_no_ssl(self) -> None:
        conn = _conn("ws://localhost:8022/runner/ws")
        kwargs = conn._build_connect_kwargs()
        assert "ssl" not in kwargs

    def test_wss_localhost_no_ssl(self) -> None:
        conn = _conn("wss://localhost:8022/runner/ws")
        kwargs = conn._build_connect_kwargs()
        # localhost dev stays plaintext even if scheme is wss.
        assert kwargs.get("ssl") is None

    def test_wss_remote_uses_provided_context(self) -> None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        conn = _conn("wss://cp.example.com/runner/ws", ssl_context=ctx)
        kwargs = conn._build_connect_kwargs()
        assert kwargs.get("ssl") is ctx

    def test_wss_remote_without_context_uses_default_tls(self) -> None:
        conn = _conn("wss://cp.example.com/runner/ws")
        kwargs = conn._build_connect_kwargs()
        # Non-localhost wss with no explicit context: still TLS (default verify).
        assert isinstance(kwargs.get("ssl"), ssl.SSLContext)


@pytest.mark.runner_unit
@pytest.mark.asyncio
async def test_connect_passes_ssl_for_remote_wss() -> None:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    conn = _conn("wss://cp.example.com/runner/ws", ssl_context=ctx)
    conn._authenticate = AsyncMock()

    captured = {}

    async def fake_connect(url, **kwargs):
        captured.update(kwargs)
        ws = AsyncMock()
        ws.recv = AsyncMock(side_effect=__import__("asyncio").CancelledError)
        return ws

    with patch.object(websockets, "connect", side_effect=fake_connect):
        await conn.connect()

    assert captured.get("ssl") is ctx
