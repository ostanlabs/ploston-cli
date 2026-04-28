"""Inspector event hub: consumes CP SSE, fans out to browser clients.

Emits the Live Event Envelope described in the spec:
    server_status / tools_changed / refresh_started / refresh_completed / heartbeat
"""

import asyncio
import logging
from typing import Any

from .models import build_overview
from .proxy import InspectorProxy, InspectorProxyError

logger = logging.getLogger(__name__)

QUEUE_MAXSIZE = 256

# Belt-and-braces: if no `notifications/tools/list_changed` arrives within
# this window, rebuild the overview on the next read anyway. Catches any
# CP-side path that mutates the tool surface without firing the notification.
DEFAULT_CACHE_TTL_SECONDS = 30.0


class EventHub:
    """Fan-out hub coordinating CP SSE → browser SSE subscribers."""

    def __init__(
        self,
        proxy: InspectorProxy,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self.proxy = proxy
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._cache: dict[str, Any] | None = None
        self._cache_built_at: float = 0.0
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache_lock = asyncio.Lock()
        self._cp_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

    # ── Cache ────────────────────────────────────────────────
    async def get_overview(self) -> dict[str, Any]:
        async with self._cache_lock:
            if self._cache is None or self._is_cache_stale():
                self._cache = await build_overview(self.proxy)
                self._cache_built_at = asyncio.get_running_loop().time()
            return self._cache

    def _is_cache_stale(self) -> bool:
        if self._cache_ttl_seconds <= 0:
            return False
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            return False
        return (now - self._cache_built_at) >= self._cache_ttl_seconds

    async def _refresh_cache(self) -> dict[str, Any]:
        async with self._cache_lock:
            self._cache = await build_overview(self.proxy)
            self._cache_built_at = asyncio.get_running_loop().time()
            return self._cache

    # ── Subscribers ──────────────────────────────────────────
    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def broadcast(self, event: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except asyncio.QueueEmpty:
                    pass

    # ── Background tasks ─────────────────────────────────────
    async def start(self) -> None:
        await self.get_overview()
        self._cp_task = asyncio.create_task(self._cp_subscriber_loop(), name="inspector-cp-sse")
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="inspector-heartbeat"
        )

    async def stop(self) -> None:
        for task in (self._cp_task, self._heartbeat_task):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(15.0)
                self.broadcast({"event": "heartbeat", "data": {"ts": _now()}})
        except asyncio.CancelledError:
            raise

    async def _cp_subscriber_loop(self) -> None:
        try:
            async for evt in self.proxy.subscribe_cp_events():
                await self._handle_cp_event(evt)
        except asyncio.CancelledError:
            raise
        except InspectorProxyError as e:
            logger.error(f"[inspector] CP SSE subscriber stopped: {e}")
            self.broadcast(
                {
                    "event": "server_status",
                    "data": {"server_id": "cp", "status": "disconnected"},
                }
            )

    async def _handle_cp_event(self, evt: dict[str, Any]) -> None:
        if evt.get("_meta") == "reconnected":
            self.broadcast(
                {
                    "event": "server_status",
                    "data": {"server_id": "cp", "status": "connected"},
                }
            )
            await self._rebuild_and_diff()
            return

        method = evt.get("method")
        if method == "notifications/tools/list_changed":
            await self._rebuild_and_diff()

    async def _rebuild_and_diff(self) -> None:
        old = self._cache or {"servers": [], "tools": []}
        try:
            new = await self._refresh_cache()
        except InspectorProxyError as e:
            logger.warning(f"[inspector] rebuild failed: {e}")
            return

        old_tools = {t["name"]: t for t in old.get("tools", [])}
        new_tools = {t["name"]: t for t in new.get("tools", [])}

        added = [t for n, t in new_tools.items() if n not in old_tools]
        removed = [t for n, t in old_tools.items() if n not in new_tools]
        updated = [t for n, t in new_tools.items() if n in old_tools and old_tools[n] != t]

        if added or removed or updated:
            self.broadcast(
                {
                    "event": "tools_changed",
                    "data": {
                        "added": added,
                        "removed": [t["name"] for t in removed],
                        "updated": updated,
                    },
                }
            )


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
