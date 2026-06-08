"""CR-4: the runner daemon must survive consecutive CP drops.

The pre-fix bug: _handle_disconnect() ran INLINE inside the receive loop and
completed the reconnect (status->CONNECTED) before the old receive task ended.
run()'s `if status == RECONNECTING` guard was then False, so run() fell to
`break` and the daemon exited even though the reconnect succeeded.

These tests drive run() through 2 consecutive drops and assert it keeps serving.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import websockets

from ploston_cli.runner.connection import RunnerConnection
from ploston_cli.runner.types import RunnerConfig, RunnerConnectionStatus


@pytest.fixture
def cfg() -> RunnerConfig:
    return RunnerConfig(
        control_plane_url="wss://cp.example.com/runner/ws",
        auth_token="test-token",
        runner_name="test-runner",
        reconnect_delay=0.01,
        max_reconnect_delay=0.02,
        max_reconnect_attempts=3,
        heartbeat_interval=100.0,
    )


def _make_dropping_ws(drops: list):
    """Build a mock ws whose recv() raises ConnectionClosed `len(drops)` times.

    Each ws instance represents one physical connection. The first N connections
    drop immediately; the final connection blocks forever (stays connected).
    """

    def factory():
        ws = AsyncMock()
        if drops:
            drops.pop(0)

            async def recv_drop():
                # Yield once so run() can await the task, then drop.
                await asyncio.sleep(0)
                raise websockets.ConnectionClosed(None, None)

            ws.recv = AsyncMock(side_effect=recv_drop)
        else:

            async def recv_block():
                await asyncio.sleep(3600)

            ws.recv = AsyncMock(side_effect=recv_block)
        return ws

    return factory


@pytest.mark.runner_unit
@pytest.mark.asyncio
async def test_run_survives_two_consecutive_drops(cfg: RunnerConfig) -> None:
    """run() must NOT return after 2 drops; runner stays CONNECTED + serving."""
    connection = RunnerConnection(config=cfg)

    # 2 connections that drop + then stable connections.
    ws_factory = _make_dropping_ws(drops=[1, 1])

    async def mock_connect(*args, **kwargs):
        return ws_factory()

    connection._authenticate = AsyncMock()

    with patch.object(websockets, "connect", side_effect=mock_connect):
        run_task = asyncio.create_task(connection.run())

        # Give the reconnect machinery time to process both drops.
        for _ in range(200):
            await asyncio.sleep(0.01)
            if run_task.done():
                break
            if (
                connection.status == RunnerConnectionStatus.CONNECTED
                and connection._reconnects_completed >= 2
            ):
                break

        # The daemon must still be alive (run() has not returned).
        assert not run_task.done(), "run() exited despite successful reconnects"
        assert connection.status == RunnerConnectionStatus.CONNECTED
        assert connection._reconnects_completed >= 2

        await connection.disconnect()
        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except (TimeoutError, asyncio.CancelledError):
            run_task.cancel()


@pytest.mark.runner_unit
@pytest.mark.asyncio
async def test_run_exits_when_reconnect_exhausted(cfg: RunnerConfig) -> None:
    """If every reconnect attempt fails, run() should return (graceful exit)."""
    connection = RunnerConnection(config=cfg)

    call = {"n": 0}

    async def mock_connect(*args, **kwargs):
        call["n"] += 1
        if call["n"] == 1:
            ws = AsyncMock()

            async def recv_drop():
                await asyncio.sleep(0)
                raise websockets.ConnectionClosed(None, None)

            ws.recv = AsyncMock(side_effect=recv_drop)
            return ws
        raise ConnectionError("refused")

    connection._authenticate = AsyncMock()

    with patch.object(websockets, "connect", side_effect=mock_connect):
        await asyncio.wait_for(connection.run(), timeout=5.0)

    assert connection.status == RunnerConnectionStatus.DISCONNECTED
    assert connection._should_run is False
