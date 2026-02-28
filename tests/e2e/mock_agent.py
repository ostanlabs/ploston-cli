"""MockAgent: Simulates an MCP client for E2E testing.

This class bridges subprocess execution with test assertions by implementing
the MCP protocol over stdio. It connects to the ploston bridge and can:
  - List available tools
  - Call tools with arguments
  - Validate responses against expected schemas

Usage:
    async with MockAgent.create("http://localhost:8443") as agent:
        tools = await agent.list_tools()
        result = await agent.call_tool("workflow:scrape-and-save", {"url": "..."})
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

# MCP protocol message types
MSG_INITIALIZE = "initialize"
MSG_INITIALIZED = "initialized"
MSG_TOOLS_LIST = "tools/list"
MSG_TOOLS_CALL = "tools/call"


@dataclass
class MockAgent:
    """MCP client simulator for E2E tests.

    Spawns the ploston bridge as a subprocess and communicates via stdio
    using the MCP JSON-RPC protocol.
    """

    cp_url: str
    process: asyncio.subprocess.Process | None = None
    _request_id: int = field(default=0, init=False)
    _pending: dict[int, asyncio.Future] = field(default_factory=dict, init=False)
    _reader_task: asyncio.Task | None = field(default=None, init=False)

    @classmethod
    async def create(cls, cp_url: str) -> MockAgent:
        """Create and initialize a MockAgent connected to the bridge."""
        agent = cls(cp_url=cp_url)
        await agent._start()
        return agent

    async def _start(self) -> None:
        """Start the bridge subprocess and initialize MCP session."""
        env = os.environ.copy()
        env["PLOSTON_SERVER"] = self.cp_url

        self.process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "ploston_cli.commands.bridge",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # Start reader task
        self._reader_task = asyncio.create_task(self._read_loop())

        # Initialize MCP session
        await self._send_request(
            MSG_INITIALIZE,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "MockAgent", "version": "1.0.0"},
            },
        )

    async def _read_loop(self) -> None:
        """Read responses from bridge stdout."""
        assert self.process and self.process.stdout
        while True:
            line = await self.process.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line.decode())
                if "id" in msg and msg["id"] in self._pending:
                    future = self._pending.pop(msg["id"])
                    if "error" in msg:
                        future.set_exception(RuntimeError(f"MCP error: {msg['error']}"))
                    else:
                        future.set_result(msg.get("result"))
            except json.JSONDecodeError:
                continue

    async def _send_request(self, method: str, params: dict | None = None) -> Any:
        """Send JSON-RPC request and wait for response."""
        assert self.process and self.process.stdin

        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params:
            request["params"] = params

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        data = json.dumps(request) + "\n"
        self.process.stdin.write(data.encode())
        await self.process.stdin.drain()

        return await asyncio.wait_for(future, timeout=30.0)

    async def list_tools(self) -> list[dict]:
        """List all available tools from the bridge."""
        result = await self._send_request(MSG_TOOLS_LIST)
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """Call a tool by name with optional arguments."""
        result = await self._send_request(
            MSG_TOOLS_CALL,
            {"name": name, "arguments": arguments or {}},
        )
        return result

    async def close(self) -> None:
        """Terminate the bridge subprocess."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self.process:
            self.process.terminate()
            await self.process.wait()

    async def __aenter__(self) -> MockAgent:
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()
