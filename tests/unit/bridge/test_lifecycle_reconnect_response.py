"""H-10 regression: queued requests must receive a response after reconnect.

Contract (fail-fast): when the bridge reconnects, every request that was
queued during the reconnect window MUST receive a definitive JSON-RPC response
delivered back to the client.  No request may be left without a response (which
would hang the MCP client that issued it).

The chosen behavior is fail-fast: instead of silently replaying queued
requests and dropping the proxy's response (the H-10 bug), the bridge emits a
well-formed JSON-RPC *error* response for each queued request and delivers it
through a response sink, so the client gets a definitive, retryable error
rather than hanging forever.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ploston_cli.bridge.errors import BRIDGE_CONNECTION_ERROR
from ploston_cli.bridge.lifecycle import BridgeLifecycle
from ploston_cli.bridge.proxy import BridgeProxy


def _make_proxy():
    proxy = MagicMock(spec=BridgeProxy)
    proxy.send_request = AsyncMock(return_value={"result": {}})
    proxy.close = AsyncMock()
    return proxy


class TestReconnectDeliversResponse:
    """H-10: client must receive a response for every queued request."""

    @pytest.mark.asyncio
    async def test_queued_request_gets_response_after_reconnect(self):
        """A request queued during reconnect receives a response via the sink."""
        proxy = _make_proxy()
        lifecycle = BridgeLifecycle(proxy=proxy)

        delivered: list[dict] = []

        async def sink(response: dict) -> None:
            delivered.append(response)

        lifecycle.is_reconnecting = True
        lifecycle.queue_request({"jsonrpc": "2.0", "id": 42, "method": "tools/list"})

        await lifecycle.on_reconnect_success(response_sink=sink)

        # The client must get *something* back for id 42 — never nothing.
        assert len(delivered) == 1, "queued request received no response (would hang)"
        resp = delivered[0]
        assert resp["id"] == 42
        assert resp["jsonrpc"] == "2.0"
        # Fail-fast: it is a well-formed JSON-RPC error the client can act on.
        assert "error" in resp
        assert isinstance(resp["error"]["code"], int)
        assert resp["error"]["code"] == BRIDGE_CONNECTION_ERROR
        assert resp["error"]["message"]

    @pytest.mark.asyncio
    async def test_every_queued_request_id_is_answered(self):
        """Multiple queued requests each get exactly one response, matched by id."""
        proxy = _make_proxy()
        lifecycle = BridgeLifecycle(proxy=proxy)

        delivered: list[dict] = []

        async def sink(response: dict) -> None:
            delivered.append(response)

        lifecycle.is_reconnecting = True
        ids = [1, 2, 3]
        for rid in ids:
            lifecycle.queue_request({"jsonrpc": "2.0", "id": rid, "method": "test"})

        await lifecycle.on_reconnect_success(response_sink=sink)

        answered_ids = sorted(r["id"] for r in delivered)
        assert answered_ids == ids
        assert lifecycle.request_queue.empty()
        assert lifecycle.is_reconnecting is False

    @pytest.mark.asyncio
    async def test_notification_without_id_gets_no_response(self):
        """JSON-RPC notifications (no id) must not produce a response."""
        proxy = _make_proxy()
        lifecycle = BridgeLifecycle(proxy=proxy)

        delivered: list[dict] = []

        async def sink(response: dict) -> None:
            delivered.append(response)

        lifecycle.is_reconnecting = True
        # Notification: no "id" member.
        lifecycle.queue_request({"jsonrpc": "2.0", "method": "notifications/cancelled"})

        await lifecycle.on_reconnect_success(response_sink=sink)

        assert delivered == [], "notifications must not receive a response"
        assert lifecycle.request_queue.empty()

    @pytest.mark.asyncio
    async def test_fail_fast_does_not_replay_to_proxy(self):
        """Fail-fast contract: queued requests are NOT re-sent to the CP."""
        proxy = _make_proxy()
        lifecycle = BridgeLifecycle(proxy=proxy)

        async def sink(response: dict) -> None:
            pass

        lifecycle.is_reconnecting = True
        lifecycle.queue_request({"jsonrpc": "2.0", "id": 7, "method": "tools/call"})

        await lifecycle.on_reconnect_success(response_sink=sink)

        # No silent replay (which dropped the response in the H-10 bug).
        proxy.send_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_sink_does_not_crash(self):
        """Backward-compat: on_reconnect_success() with no sink still drains."""
        proxy = _make_proxy()
        lifecycle = BridgeLifecycle(proxy=proxy)

        lifecycle.is_reconnecting = True
        lifecycle.queue_request({"jsonrpc": "2.0", "id": 9, "method": "test"})

        # Must not raise even without a sink.
        await lifecycle.on_reconnect_success()

        assert lifecycle.request_queue.empty()
        assert lifecycle.is_reconnecting is False
