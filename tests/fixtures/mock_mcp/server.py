#!/usr/bin/env python3
"""Mock MCP Server for scenario testing.

This server implements the MCP protocol and returns canned responses
from responses.json. It supports both stdio and HTTP modes.

Usage:
    # Stdio mode (default) - for bridge testing
    python server.py

    # HTTP mode - for direct testing
    python server.py --http --port 8080
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Load responses from JSON file
RESPONSES_FILE = Path(__file__).parent / "responses.json"


def load_responses() -> dict:
    """Load canned responses from JSON file."""
    if RESPONSES_FILE.exists():
        return json.loads(RESPONSES_FILE.read_text())
    return {"tools/list": {"tools": []}, "tools/call": {}}


RESPONSES = load_responses()


def handle_request(method: str, params: dict | None = None) -> dict:
    """Handle an MCP request and return appropriate response."""
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mock-mcp", "version": "1.0.0"},
        }

    if method == "tools/list":
        return RESPONSES.get("tools/list", {"tools": []})

    if method == "tools/call":
        tool_name = params.get("name", "") if params else ""
        tool_responses = RESPONSES.get("tools/call", {})
        if tool_name in tool_responses:
            return tool_responses[tool_name]
        # Default error response for unknown tools
        return {
            "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            "isError": True,
        }

    if method == "resources/list":
        return RESPONSES.get("resources/list", {"resources": []})

    if method == "prompts/list":
        return RESPONSES.get("prompts/list", {"prompts": []})

    # Unknown method
    return {"error": {"code": -32601, "message": f"Method not found: {method}"}}


def run_stdio_mode() -> None:
    """Run server in stdio mode (JSON-RPC over stdin/stdout)."""
    for line in sys.stdin:
        try:
            request = json.loads(line.strip())
            method = request.get("method", "")
            params = request.get("params")
            request_id = request.get("id")

            result = handle_request(method, params)

            response = {"jsonrpc": "2.0", "id": request_id}
            if "error" in result:
                response["error"] = result["error"]
            else:
                response["result"] = result

            print(json.dumps(response), flush=True)

        except json.JSONDecodeError:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
            print(json.dumps(error_response), flush=True)


def run_http_mode(port: int) -> None:
    """Run server in HTTP mode."""
    try:
        from http.server import BaseHTTPRequestHandler, HTTPServer
    except ImportError:
        print("HTTP mode requires http.server module", file=sys.stderr)
        sys.exit(1)

    class MCPHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            """Handle GET requests (health check)."""
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "healthy"}).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode()
            try:
                request = json.loads(body)
                method = request.get("method", "")
                params = request.get("params")
                result = handle_request(method, params)
                response = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass  # Suppress logging

    server = HTTPServer(("0.0.0.0", port), MCPHandler)
    print(f"Mock MCP server running on http://0.0.0.0:{port}", file=sys.stderr)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock MCP Server")
    parser.add_argument("--http", action="store_true", help="Run in HTTP mode")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    args = parser.parse_args()

    if args.http:
        run_http_mode(args.port)
    else:
        run_stdio_mode()


if __name__ == "__main__":
    main()
