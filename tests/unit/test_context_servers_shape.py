"""Tests for ContextServersShape (S-317, T-1020, T-1021).

Verifies:
- Sibling top-level keys preserved on round-trip
- Backup section uses standard _ploston_imported sibling pattern
- decorate_server_entry is a no-op
"""

from __future__ import annotations

import pytest

from ploston_cli.init.injection_targets.shapes import ContextServersShape


@pytest.fixture
def zed_data() -> dict:
    """Realistic Zed settings.json data with many sibling keys."""
    return {
        "theme": "One Dark",
        "telemetry": {"diagnostics": False, "metrics": False},
        "vim_mode": True,
        "tab_size": 4,
        "languages": {"Python": {"tab_size": 4, "formatter": "ruff"}},
        "context_servers": {
            "github": {"command": "npx", "args": ["-y", "@mcp/github"]},
        },
    }


class TestContextServersShapePreservesSiblings:
    """S-317 gate: sibling top-level keys preserved on round-trip."""

    def test_get_servers_returns_context_servers(self, zed_data):
        shape = ContextServersShape()
        servers = shape.get_servers(zed_data)
        assert "github" in servers
        assert servers["github"]["command"] == "npx"

    def test_set_servers_preserves_siblings(self, zed_data):
        shape = ContextServersShape()
        new_servers = {
            "github": {"command": "npx", "args": ["-y", "@mcp/github"]},
            "ploston": {"command": "ploston", "args": ["bridge"]},
        }
        result = shape.set_servers(zed_data, new_servers)

        # Sibling keys intact
        assert result["theme"] == "One Dark"
        assert result["telemetry"] == {"diagnostics": False, "metrics": False}
        assert result["vim_mode"] is True
        assert result["tab_size"] == 4
        assert result["languages"]["Python"]["formatter"] == "ruff"
        # Servers updated
        assert "ploston" in result["context_servers"]
        assert "github" in result["context_servers"]

    def test_backup_section_uses_ploston_imported(self, zed_data):
        shape = ContextServersShape()

        # Initially no backup
        assert shape.get_backup_section(zed_data) == {}

        # Set backup
        backup = {"github": {"command": "npx", "args": ["-y", "@mcp/github"]}}
        result = shape.set_backup_section(zed_data, backup)
        assert result["_ploston_imported"]["github"]["command"] == "npx"
        # Siblings intact
        assert result["theme"] == "One Dark"

        # Strip backup
        stripped = shape.strip_backup_section(result)
        assert "_ploston_imported" not in stripped
        assert stripped["theme"] == "One Dark"

    def test_decorate_server_entry_is_noop(self):
        shape = ContextServersShape()
        entry = {"command": "ploston", "args": ["bridge"]}
        decorated = shape.decorate_server_entry(entry)
        assert decorated == entry
        assert "type" not in decorated

    def test_missing_context_servers_returns_empty(self):
        shape = ContextServersShape()
        data = {"theme": "dark"}
        assert shape.get_servers(data) == {}
