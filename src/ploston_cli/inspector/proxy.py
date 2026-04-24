"""InspectorProxy — long-lived HTTP client wrapper for the Control Plane.

Modeled after BridgeProxy's lifecycle (persistent httpx.AsyncClient via
``_ensure_client()`` + explicit ``close()``), but exposes the broader
PlostClient-style REST surface the inspector needs.
"""

import asyncio
import json
import logging
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx
from httpx_sse import aconnect_sse

logger = logging.getLogger(__name__)


class InspectorProxyError(Exception):
    """Error raised by InspectorProxy operations."""


class InspectorProxy:
    """Long-lived HTTP client wrapping REST + SSE calls to the Control Plane."""

    def __init__(
        self,
        url: str,
        token: str | None = None,
        timeout: float = 30.0,
        insecure: bool = False,
    ) -> None:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid URL: {url}")

        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.insecure = insecure
        self._client: httpx.AsyncClient | None = None
        self._closed = False

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._closed:
            raise InspectorProxyError("InspectorProxy is closed")
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers=self._headers(),
                verify=not self.insecure,
            )
        return self._client

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        client = await self._ensure_client()
        url = f"{self.url}{path}"
        try:
            response = await client.get(url, params=params)
        except httpx.ConnectError as e:
            raise InspectorProxyError(f"Connection error: {e}") from e
        if response.status_code >= 400:
            raise InspectorProxyError(
                f"HTTP {response.status_code} for GET {path}: {response.text}"
            )
        return response.json()

    async def _post(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        client = await self._ensure_client()
        url = f"{self.url}{path}"
        try:
            response = await client.post(url, params=params, json=json_body)
        except httpx.ConnectError as e:
            raise InspectorProxyError(f"Connection error: {e}") from e
        if response.status_code >= 400:
            raise InspectorProxyError(
                f"HTTP {response.status_code} for POST {path}: {response.text}"
            )
        return response.json()

    # ── REST surface ─────────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        return await self._get("/health")

    async def get_capabilities(self) -> dict[str, Any]:
        return await self._get("/api/v1/capabilities")

    async def get_config(self, section: str | None = None) -> dict[str, Any]:
        params = {"section": section} if section else None
        return await self._get("/api/v1/config", params=params)

    async def list_runners(self) -> list[dict[str, Any]]:
        response = await self._get("/api/v1/runners")
        if isinstance(response, dict) and "runners" in response:
            return response["runners"]
        return response

    async def get_runner(self, name: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/runners/{name}")

    async def list_tools(self) -> list[dict[str, Any]]:
        response = await self._get("/api/v1/tools")
        if isinstance(response, dict) and "tools" in response:
            return response["tools"]
        return response

    async def get_tool(self, name: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/tools/{name}")

    async def refresh_tools(self, server: str | None = None) -> dict[str, Any]:
        params = {"server": server} if server else None
        return await self._post("/api/v1/tools/refresh", params=params)

    async def get_cp_mcp_status(self, name: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/mcp-servers/{name}/status")

    async def get_runner_mcp_status(self, runner: str, mcp: str) -> dict[str, Any]:
        return await self._get(f"/api/v1/runners/{runner}/mcps/{mcp}/status")

    async def mcp_tools_list(self, tags: list[str] | None = None) -> list[dict[str, Any]]:
        """Call the CP's JSON-RPC ``tools/list`` endpoint.

        Returns tools with their exact MCP schema (the same shape an agent
        connecting through ``ploston bridge`` would see). Optional ``tags``
        applies the CP's match-all tag filter (e.g. ``kind:workflow_mgmt``).
        """
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {"tags": tags} if tags else {},
        }
        resp = await self._post("/mcp", json_body=payload)
        if isinstance(resp, dict):
            if "error" in resp:
                raise InspectorProxyError(f"MCP tools/list failed: {resp['error']}")
            return resp.get("result", {}).get("tools", [])
        return []

    # ── SSE subscription ─────────────────────────────────────────

    async def subscribe_cp_events(
        self,
        max_reconnect_attempts: int = 5,
        reconnect_delay: float = 1.0,
    ) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to CP notifications with exponential-backoff reconnect.

        Duplicated from BridgeProxy.subscribe_notifications (intentional for v0,
        per INSPECTOR_SERVICE_SPEC T-B2). Yields parsed JSON payloads. Emits
        a synthetic ``{"_meta": "reconnected"}`` event after each successful
        reconnect so consumers can perform a post-outage refresh.
        """
        url = f"{self.url}/mcp/sse"
        reconnect_attempts = 0
        had_prior_connection = False

        while True:
            client = await self._ensure_client()
            try:
                async with aconnect_sse(client, "GET", url) as event_source:
                    if had_prior_connection:
                        yield {"_meta": "reconnected"}
                    reconnect_attempts = 0
                    had_prior_connection = True
                    logger.info(f"[inspector] CP SSE connected: {url}")

                    async for sse in event_source.aiter_sse():
                        if sse.data:
                            try:
                                yield json.loads(sse.data)
                            except json.JSONDecodeError:
                                logger.warning(f"[inspector] Invalid JSON in SSE: {sse.data}")
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as e:
                reconnect_attempts += 1
                logger.warning(
                    f"[inspector] CP SSE dropped "
                    f"(attempt {reconnect_attempts}/{max_reconnect_attempts}): {e}"
                )
                if reconnect_attempts >= max_reconnect_attempts:
                    raise InspectorProxyError(
                        f"CP SSE connection failed after {max_reconnect_attempts} attempts: {e}"
                    ) from e
                delay = reconnect_delay * (2 ** (reconnect_attempts - 1))
                await asyncio.sleep(delay)

    async def close(self) -> None:
        self._closed = True
        if self._client:
            await self._client.aclose()
            self._client = None
