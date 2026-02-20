"""HTTP client for Ploston REST API.

This module provides the HTTP client for communicating with Ploston servers.
The CLI is a thin client that delegates all operations to the server via HTTP.
"""

from typing import Any

import httpx


class PlostClientError(Exception):
    """Error from Ploston API client."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class PlostClient:
    """HTTP client for Ploston REST API.

    All operations are delegated to the server via HTTP.
    """

    def __init__(self, base_url: str, timeout: float = 30.0, insecure: bool = False):
        """Initialize client.

        Args:
            base_url: Server URL (e.g., http://localhost:8080)
            timeout: Request timeout in seconds
            insecure: Skip SSL certificate verification (like curl -k)
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.insecure = insecure
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "PlostClient":
        """Enter async context."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
            verify=not self.insecure,
        )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure client is initialized."""
        if not self._client:
            raise PlostClientError("Client not initialized. Use 'async with' context.")
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make HTTP request to server.

        Args:
            method: HTTP method
            path: API path (e.g., /api/v1/workflows)
            json: JSON body for POST/PUT
            params: Query parameters

        Returns:
            Response JSON as dict

        Raises:
            PlostClientError: On connection or HTTP errors
        """
        client = self._ensure_client()
        try:
            response = await client.request(method, path, json=json, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError:
            raise PlostClientError(
                f"Cannot connect to Ploston server at {self.base_url}\n"
                "Is the server running? Start it with: ploston-server"
            )
        except httpx.HTTPStatusError as e:
            # Try to extract error message from response
            try:
                error_data = e.response.json()
                message = error_data.get("detail", str(e))
            except Exception:
                message = str(e)
            raise PlostClientError(message, status_code=e.response.status_code)
        except httpx.TimeoutException:
            raise PlostClientError(f"Request timed out after {self.timeout}s")

    # -------------------------------------------------------------------------
    # Capabilities
    # -------------------------------------------------------------------------

    async def get_capabilities(self) -> dict[str, Any]:
        """Get server capabilities for tier detection.

        Returns:
            Capabilities dict with tier, version, features, limits
        """
        return await self._request("GET", "/api/v1/capabilities")

    # -------------------------------------------------------------------------
    # Workflows
    # -------------------------------------------------------------------------

    async def list_workflows(self) -> list[dict[str, Any]]:
        """List all workflows.

        Returns:
            List of workflow summaries
        """
        response = await self._request("GET", "/api/v1/workflows")
        # API returns {"workflows": [...], "total": ..., ...}
        return response.get("workflows", [])

    async def get_workflow(self, name: str) -> dict[str, Any]:
        """Get workflow details.

        Args:
            name: Workflow name

        Returns:
            Workflow details dict
        """
        return await self._request("GET", f"/api/v1/workflows/{name}")

    async def execute_workflow(
        self,
        name: str,
        inputs: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow.

        Args:
            name: Workflow name
            inputs: Workflow inputs
            timeout: Execution timeout in seconds

        Returns:
            Execution result dict
        """
        body: dict[str, Any] = {"inputs": inputs or {}}
        if timeout:
            body["timeout"] = timeout
        return await self._request("POST", f"/api/v1/workflows/{name}/execute", json=body)

    # -------------------------------------------------------------------------
    # Tools
    # -------------------------------------------------------------------------

    async def list_tools(
        self,
        source: str | None = None,
        server: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List available tools.

        Args:
            source: Filter by source (mcp, system)
            server: Filter by MCP server name
            status: Filter by status (available, unavailable)

        Returns:
            List of tool summaries
        """
        params: dict[str, Any] = {}
        if source:
            params["source"] = source
        if server:
            params["server"] = server
        if status:
            params["status"] = status
        response = await self._request("GET", "/api/v1/tools", params=params or None)
        # API returns {"tools": [...]} but we want just the list
        if isinstance(response, dict) and "tools" in response:
            return response["tools"]
        return response

    async def get_tool(self, name: str) -> dict[str, Any]:
        """Get tool details.

        Args:
            name: Tool name

        Returns:
            Tool details dict
        """
        return await self._request("GET", f"/api/v1/tools/{name}")

    async def refresh_tools(self, server: str | None = None) -> dict[str, Any]:
        """Refresh tool schemas from MCP servers.

        Args:
            server: Refresh specific server only

        Returns:
            Refresh result dict
        """
        params = {"server": server} if server else None
        return await self._request("POST", "/api/v1/tools/refresh", params=params)

    # -------------------------------------------------------------------------
    # Config (server config, not CLI config)
    # -------------------------------------------------------------------------

    async def get_config(self, section: str | None = None) -> dict[str, Any]:
        """Get server configuration.

        Args:
            section: Specific section to retrieve

        Returns:
            Configuration dict
        """
        params = {"section": section} if section else None
        return await self._request("GET", "/api/v1/config", params=params)

    # -------------------------------------------------------------------------
    # Health
    # -------------------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        """Check server health.

        Returns:
            Health status dict
        """
        return await self._request("GET", "/health")

    # -------------------------------------------------------------------------
    # Runners
    # -------------------------------------------------------------------------

    async def create_runner(
        self,
        name: str,
        mcps: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new runner.

        Args:
            name: Runner name
            mcps: Optional MCP server configurations

        Returns:
            Runner creation response with token and install command
        """
        body: dict[str, Any] = {"name": name}
        if mcps:
            body["mcps"] = mcps
        return await self._request("POST", "/api/v1/runners", json=body)

    async def list_runners(
        self,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all runners.

        Args:
            status: Filter by status (connected, disconnected)

        Returns:
            List of runner summaries
        """
        params: dict[str, Any] = {}
        if status:
            params["status"] = status
        response = await self._request("GET", "/api/v1/runners", params=params or None)
        return response.get("runners", [])

    async def get_runner(self, name: str) -> dict[str, Any]:
        """Get runner details.

        Args:
            name: Runner name

        Returns:
            Runner details dict
        """
        return await self._request("GET", f"/api/v1/runners/{name}")

    async def delete_runner(self, name: str) -> dict[str, Any]:
        """Delete a runner.

        Args:
            name: Runner name

        Returns:
            Deletion result dict
        """
        return await self._request("DELETE", f"/api/v1/runners/{name}")

    async def regenerate_runner_token(self, name: str) -> dict[str, Any]:
        """Regenerate a runner's authentication token.

        Args:
            name: Runner name

        Returns:
            Token response dict with name, token, and install_command
        """
        return await self._request("POST", f"/api/v1/runners/{name}/regenerate-token")

    # Config operations

    async def get_config_diff(self) -> dict[str, Any]:
        """Get diff between current config and staged changes.

        Returns:
            Diff response dict with diff, has_changes, and in_config_mode
        """
        return await self._request("GET", "/api/v1/config/diff")
