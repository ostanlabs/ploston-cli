"""Shared fixtures for user scenario tests.

These tests validate end-to-end user journeys across CLI, bridge, runner,
and control plane. They are organized by the USER_SCENARIO_AUTOMATION_MAP.md
document (S-01 through S-44).

Layers:
  Layer 1 (no backend): S-01, S-04, S-05, S-42, S-43 — pure CLI, no Docker
  Layer 2 (Docker Compose): S-02 through S-41, S-44 — CP + mock MCPs
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import requests

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLOSTON_SERVER_URL = os.environ.get("PLOSTON_SERVER_URL", "http://localhost:8443")
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
MOCK_MCP_DIR = FIXTURES_DIR / "mock_mcp"
WORKFLOWS_DIR = FIXTURES_DIR / "workflows"


# ---------------------------------------------------------------------------
# Health & Server Fixtures (Layer 2)
# ---------------------------------------------------------------------------


def wait_for_health(url: str, timeout: int = 60) -> bool:
    """Wait for a service to become healthy."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            response = requests.get(f"{url}/health", timeout=5)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(2)
    return False


@pytest.fixture(scope="module")
def cp_url() -> str:
    """Control Plane URL. Skips Layer 2 tests if CP unreachable."""
    url = PLOSTON_SERVER_URL
    if not wait_for_health(url, timeout=10):
        pytest.skip(f"CP not reachable at {url}. Start with: make test-setup-docker")
    return url


@pytest.fixture(scope="module")
def api_url(cp_url: str) -> str:
    """REST API base URL."""
    return f"{cp_url}/api/v1"


@pytest.fixture(scope="module")
def ws_url(cp_url: str) -> str:
    """WebSocket URL for runner connections."""
    host = cp_url.replace("http://", "").replace("https://", "")
    return f"ws://{host}/api/v1/runner/ws"


# ---------------------------------------------------------------------------
# CLI Fixture (Layer 1 — no Docker needed)
# ---------------------------------------------------------------------------


@pytest.fixture
def cli(tmp_path):
    """Fixture providing a CLI runner function.

    Returns a function that runs ploston CLI commands and returns a result object.
    """
    import subprocess
    from dataclasses import dataclass

    @dataclass
    class CLIResult:
        returncode: int
        stdout: str
        stderr: str

    def run_cli(*args, check: bool = True, timeout: int = 30) -> CLIResult:
        """Run ploston CLI with given arguments."""
        result = subprocess.run(
            ["ploston", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(tmp_path),
        )
        return CLIResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    return run_cli


# ---------------------------------------------------------------------------
# Mock Claude Config Fixture (Layer 1)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_claude_config(tmp_path, monkeypatch):
    """Create a mock Claude Desktop config for testing.

    Sets up a temporary HOME with a Claude Desktop config file.
    """
    import platform

    # Create config directory based on platform
    if platform.system() == "Darwin":
        config_dir = tmp_path / "Library" / "Application Support" / "Claude"
    else:
        config_dir = tmp_path / ".config" / "Claude"

    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "claude_desktop_config.json"

    # Write sample config with MCP servers
    config_content = {
        "mcpServers": {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            },
            "memory": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-memory"],
            },
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
            },
        }
    }
    config_file.write_text(json.dumps(config_content, indent=2))

    # Set HOME to temp path
    monkeypatch.setenv("HOME", str(tmp_path))
    if platform.system() != "Darwin":
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))

    return config_file


# ---------------------------------------------------------------------------
# Workflow Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workflow_dir() -> Path:
    """Path to test workflow YAML fixtures."""
    d = WORKFLOWS_DIR
    if not d.exists():
        pytest.skip("Workflow fixtures not found at tests/fixtures/workflows/")
    return d


@pytest.fixture
def golden_dir() -> Path:
    """Path to golden file fixtures for regression."""
    d = WORKFLOWS_DIR / "golden"
    if not d.exists():
        pytest.skip("Golden fixtures not found")
    return d
