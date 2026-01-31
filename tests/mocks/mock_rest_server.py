"""MockRestServer - Mock REST API server simulating CP for CLI testing.

Implements S-189: Test Infrastructure
- MockRestServer class
- Runner CRUD endpoints
- Tool endpoints
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel


class RunnerCreateRequest(BaseModel):
    """Request body for creating a runner."""
    name: str
    mcps: list[str] | None = None


class MockRestServer:
    """Mock REST API server simulating CP for CLI testing.

    This mock server provides:
    - Runner CRUD endpoints (/api/v1/runners)
    - Tool list endpoint (/api/v1/tools)
    - Configurable responses for testing edge cases

    Example:
        server = MockRestServer()
        client = server.get_test_client()

        # Create a runner
        response = client.post("/api/v1/runners", json={"name": "test-runner"})
        assert response.status_code == 201

        # List runners
        response = client.get("/api/v1/runners")
        assert len(response.json()["runners"]) == 1
    """

    def __init__(self):
        """Initialize MockRestServer."""
        self.app = FastAPI(title="Mock Ploston API")
        self.created_runners: dict[str, dict] = {}
        self.tools: list[dict] = []
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Set up API routes."""

        @self.app.post("/api/v1/runners", status_code=201)
        def create_runner(body: RunnerCreateRequest) -> dict:
            """Create a new runner."""
            name = body.name

            if name in self.created_runners:
                raise HTTPException(status_code=409, detail=f"Runner '{name}' already exists")

            token = f"plr_{secrets.token_hex(16)}"
            self.created_runners[name] = {
                "name": name,
                "token": token,
                "token_hash": f"hash_{token[:8]}",
                "status": "pending",
                "mcps": body.mcps or [],
                "available_tools": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_seen": None,
                "install_command": f"curl -sSL http://localhost:8080/runner/install.sh | bash -s -- --token {token}"
            }
            return self.created_runners[name]

        @self.app.get("/api/v1/runners")
        def list_runners(status: str | None = None) -> dict:
            """List all runners."""
            runners = list(self.created_runners.values())
            if status:
                runners = [r for r in runners if r["status"] == status]
            return {"runners": runners, "total": len(runners)}

        @self.app.get("/api/v1/runners/{name}")
        def get_runner(name: str) -> dict:
            """Get a specific runner."""
            if name not in self.created_runners:
                raise HTTPException(status_code=404, detail=f"Runner '{name}' not found")
            return self.created_runners[name]

        @self.app.delete("/api/v1/runners/{name}")
        def delete_runner(name: str) -> dict:
            """Delete a runner."""
            if name not in self.created_runners:
                raise HTTPException(status_code=404, detail=f"Runner '{name}' not found")
            del self.created_runners[name]
            return {"deleted": True, "name": name}

        @self.app.get("/api/v1/tools")
        def list_tools() -> dict:
            """List all available tools."""
            return {"tools": self.tools, "total": len(self.tools)}

        @self.app.get("/runner/install.sh")
        def get_install_script() -> str:
            """Get runner install script."""
            return """#!/bin/bash
# Mock install script
echo "Installing ploston-runner..."
"""

        @self.app.get("/runner/ca.crt")
        def get_ca_cert() -> str:
            """Get CA certificate."""
            return """-----BEGIN CERTIFICATE-----
MOCK_CERTIFICATE
-----END CERTIFICATE-----
"""

    def get_test_client(self) -> TestClient:
        """Get a TestClient for making requests.

        Returns:
            FastAPI TestClient instance
        """
        return TestClient(self.app)

    def add_runner(
        self,
        name: str,
        status: str = "connected",
        tools: list[str] | None = None
    ) -> dict:
        """Add a pre-configured runner.

        Args:
            name: Runner name
            status: Runner status (pending, connected, disconnected)
            tools: List of available tool names

        Returns:
            Runner dict
        """
        token = f"plr_{secrets.token_hex(16)}"
        self.created_runners[name] = {
            "name": name,
            "token": token,
            "token_hash": f"hash_{token[:8]}",
            "status": status,
            "mcps": [],
            "available_tools": tools or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_seen": datetime.now(timezone.utc).isoformat() if status == "connected" else None,
            "install_command": f"curl -sSL http://localhost:8080/runner/install.sh | bash -s -- --token {token}"
        }
        return self.created_runners[name]

    def add_tool(
        self,
        name: str,
        description: str = "",
        source: str = "local",
        runner: str | None = None
    ) -> dict:
        """Add a tool to the mock server.

        Args:
            name: Tool name
            description: Tool description
            source: Tool source (local, runner)
            runner: Runner name if source is runner

        Returns:
            Tool dict
        """
        tool = {
            "name": name,
            "description": description,
            "source": source,
            "runner": runner,
            "input_schema": {"type": "object", "properties": {}}
        }
        self.tools.append(tool)
        return tool

    def clear(self) -> None:
        """Clear all runners and tools."""
        self.created_runners.clear()
        self.tools.clear()
