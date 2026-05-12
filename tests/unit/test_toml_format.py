"""Tests for TomlFormat (S-316, T-1018, T-1019).

Verifies:
- Pure round-trip preserves comments on unmodified sections
- Modification preserves comments on *unmodified* sections (best-effort)
- Data semantics always preserved
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ploston_cli.init.injection_targets.formats import TomlFormat


@pytest.fixture
def toml_file(tmp_path: Path) -> Path:
    """Seed a TOML file with comments and multiple sections."""
    content = """\
# Global settings for Codex CLI
[settings]
model = "o3"
approval_mode = "suggest"

# MCP server definitions
[mcp_servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]

# Analytics server
[mcp_servers.analytics]
command = "python"
args = ["-m", "analytics_mcp"]
"""
    p = tmp_path / "config.toml"
    p.write_text(content, encoding="utf-8")
    return p


class TestTomlFormatRoundTrip:
    """S-316 gate: TOML round-trip preserves comments on unmodified sections."""

    def test_pure_round_trip_preserves_comments(self, toml_file: Path):
        """read → write without modification preserves byte-identical output."""
        fmt = TomlFormat()
        original = toml_file.read_text(encoding="utf-8")

        data = fmt.read(toml_file)
        fmt.write(toml_file, data)

        assert toml_file.read_text(encoding="utf-8") == original

    def test_modification_preserves_unmodified_comments(self, toml_file: Path):
        """Adding a new section preserves comments on untouched sections."""
        fmt = TomlFormat()

        data = fmt.read(toml_file)
        # Add a new server (simulates ploston injection)
        data["mcp_servers"]["ploston"] = {"command": "ploston", "args": ["bridge"]}
        fmt.write(toml_file, data)

        result = toml_file.read_text(encoding="utf-8")
        # Original comments should still be present
        assert "# Global settings for Codex CLI" in result
        assert "# MCP server definitions" in result
        assert "# Analytics server" in result
        # New entry should be present
        assert "[mcp_servers.ploston]" in result

    def test_data_semantics_always_preserved(self, toml_file: Path):
        """All data values survive a write → read cycle."""
        fmt = TomlFormat()

        data = fmt.read(toml_file)
        data["mcp_servers"]["ploston"] = {
            "command": "ploston",
            "args": ["bridge", "--cp-url", "http://localhost:8022"],
        }
        fmt.write(toml_file, data)

        data2 = fmt.read(toml_file)
        assert data2["settings"]["model"] == "o3"
        assert data2["settings"]["approval_mode"] == "suggest"
        assert list(data2["mcp_servers"]["github"]["args"]) == [
            "-y",
            "@modelcontextprotocol/server-github",
        ]
        assert list(data2["mcp_servers"]["ploston"]["args"]) == [
            "bridge",
            "--cp-url",
            "http://localhost:8022",
        ]
        assert data2["mcp_servers"]["analytics"]["command"] == "python"

    def test_empty_toml_round_trip(self, tmp_path: Path):
        """An empty TOML file can be read and written back."""
        p = tmp_path / "empty.toml"
        p.write_text("", encoding="utf-8")

        fmt = TomlFormat()
        data = fmt.read(p)
        assert dict(data) == {}

        data["mcp_servers"] = {"ploston": {"command": "ploston"}}
        fmt.write(p, data)

        data2 = fmt.read(p)
        assert data2["mcp_servers"]["ploston"]["command"] == "ploston"
