"""Tests for the inspector EventHub fan-out + diff logic."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from ploston_cli.inspector.events import EventHub


def _mk_proxy(initial_tools=None, follow_up_tools=None):
    proxy = AsyncMock()
    proxy.url = "http://cp:8022"
    proxy.get_capabilities.return_value = {"version": "1.0"}
    proxy.health.return_value = {"status": "ok"}
    proxy.get_config.return_value = {"tools": {"mcp_servers": {}}}
    proxy.list_runners.return_value = []
    proxy.get_runner.return_value = {"mcps": []}
    proxy.list_tools.side_effect = [initial_tools or [], follow_up_tools or []]
    proxy.get_cp_mcp_status.return_value = {"status": "connected"}
    proxy.get_runner_mcp_status.return_value = {"status": "connected"}
    return proxy


@pytest.mark.asyncio
async def test_subscribe_returns_unique_queues():
    proxy = _mk_proxy()
    hub = EventHub(proxy)
    q1 = hub.subscribe()
    q2 = hub.subscribe()
    assert q1 is not q2
    assert len(hub._subscribers) == 2


@pytest.mark.asyncio
async def test_broadcast_delivers_to_all_subscribers():
    proxy = _mk_proxy()
    hub = EventHub(proxy)
    q1 = hub.subscribe()
    q2 = hub.subscribe()

    hub.broadcast({"event": "heartbeat", "data": {"ts": "now"}})

    evt1 = await asyncio.wait_for(q1.get(), timeout=0.5)
    evt2 = await asyncio.wait_for(q2.get(), timeout=0.5)
    assert evt1["event"] == "heartbeat"
    assert evt2["event"] == "heartbeat"


@pytest.mark.asyncio
async def test_unsubscribe_removes_queue():
    proxy = _mk_proxy()
    hub = EventHub(proxy)
    q = hub.subscribe()
    hub.unsubscribe(q)
    assert q not in hub._subscribers


@pytest.mark.asyncio
async def test_rebuild_and_diff_emits_added_tools():
    proxy = _mk_proxy(
        initial_tools=[],
        follow_up_tools=[{"name": "new_tool", "source": "mcp", "server": "fs"}],
    )
    proxy.get_config.return_value = {"tools": {"mcp_servers": {"fs": {}}}}
    hub = EventHub(proxy)
    await hub.get_overview()  # prime cache with []

    q = hub.subscribe()
    await hub._rebuild_and_diff()

    evt = await asyncio.wait_for(q.get(), timeout=0.5)
    assert evt["event"] == "tools_changed"
    assert len(evt["data"]["added"]) == 1
    assert evt["data"]["added"][0]["name"] == "new_tool"


@pytest.mark.asyncio
async def test_rebuild_and_diff_emits_removed_tools():
    proxy = _mk_proxy(
        initial_tools=[{"name": "old_tool", "source": "mcp", "server": "fs"}],
        follow_up_tools=[],
    )
    proxy.get_config.return_value = {"tools": {"mcp_servers": {"fs": {}}}}
    hub = EventHub(proxy)
    await hub.get_overview()

    q = hub.subscribe()
    await hub._rebuild_and_diff()

    evt = await asyncio.wait_for(q.get(), timeout=0.5)
    assert evt["event"] == "tools_changed"
    assert evt["data"]["removed"] == ["old_tool"]


@pytest.mark.asyncio
async def test_handle_cp_reconnected_emits_status_event():
    proxy = _mk_proxy()
    hub = EventHub(proxy)
    await hub.get_overview()

    q = hub.subscribe()
    await hub._handle_cp_event({"_meta": "reconnected"})

    evt = await asyncio.wait_for(q.get(), timeout=0.5)
    assert evt["event"] == "server_status"
    assert evt["data"]["status"] == "connected"


@pytest.mark.asyncio
async def test_handle_cp_tools_list_changed_triggers_rebuild():
    proxy = _mk_proxy(
        initial_tools=[],
        follow_up_tools=[{"name": "x", "source": "mcp", "server": "fs"}],
    )
    proxy.get_config.return_value = {"tools": {"mcp_servers": {"fs": {}}}}
    hub = EventHub(proxy)
    await hub.get_overview()

    q = hub.subscribe()
    await hub._handle_cp_event({"method": "notifications/tools/list_changed"})

    evt = await asyncio.wait_for(q.get(), timeout=0.5)
    assert evt["event"] == "tools_changed"


@pytest.mark.asyncio
async def test_queue_full_drops_oldest():
    proxy = _mk_proxy()
    hub = EventHub(proxy)
    q = hub.subscribe()

    # Fill past the configured queue size
    for i in range(260):
        hub.broadcast({"event": "heartbeat", "data": {"seq": i}})

    # Must not raise — overflow handling drops oldest
    assert q.qsize() <= 256
