"""Unit tests for ploston init detector module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ploston_cli.init.detector import (
    ConfigDetector,
    DetectedConfig,
    ServerInfo,
    merge_configs,
)


class TestConfigDetector:
    """Tests for ConfigDetector class."""

    @pytest.fixture
    def detector(self):
        """Create a ConfigDetector instance."""
        return ConfigDetector()

    def test_detect_claude_desktop_not_found(self, detector, tmp_path):
        """Test detection when Claude Desktop config doesn't exist."""
        # Patch get_config_path to return a non-existent path
        with patch.object(detector, "get_config_path", return_value=tmp_path / "nonexistent.json"):
            result = detector.detect_source("claude_desktop")

        assert result.source == "claude_desktop"
        assert result.found is False
        assert result.servers == {}
        assert result.server_count == 0

    def test_detect_claude_desktop_found(self, detector, tmp_path):
        """Test detection when Claude Desktop config exists."""
        config_file = tmp_path / "claude_desktop_config.json"
        config_data = {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home"],
                },
                "github": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "ghp_xxx"},
                },
            }
        }
        config_file.write_text(json.dumps(config_data))

        with patch.object(detector, "get_config_path", return_value=config_file):
            result = detector.detect_source("claude_desktop")

        assert result.source == "claude_desktop"
        assert result.found is True
        assert result.path == config_file
        assert result.server_count == 2
        assert "filesystem" in result.servers
        assert "github" in result.servers
        # ServerInfo has env as a dict attribute
        assert result.servers["github"].env["GITHUB_TOKEN"] == "ghp_xxx"

    def test_detect_cursor_not_found(self, detector, tmp_path):
        """Test detection when Cursor config doesn't exist."""
        with patch.object(detector, "get_config_path", return_value=tmp_path / "nonexistent"):
            result = detector.detect_source("cursor")

        assert result.source == "cursor"
        assert result.found is False

    def test_detect_cursor_found(self, detector, tmp_path):
        """Test detection when Cursor config exists."""
        cursor_dir = tmp_path / "cursor_mcp"
        cursor_dir.mkdir()
        config_file = cursor_dir / "mcp.json"
        config_data = {
            "mcpServers": {
                "sqlite": {
                    "command": "uvx",
                    "args": ["mcp-server-sqlite", "--db-path", "/tmp/test.db"],
                }
            }
        }
        config_file.write_text(json.dumps(config_data))

        with patch.object(detector, "get_config_path", return_value=cursor_dir):
            result = detector.detect_source("cursor")

        assert result.source == "cursor"
        assert result.found is True
        assert result.server_count == 1
        assert "sqlite" in result.servers

    def test_detect_all(self, detector, tmp_path):
        """Test detecting all sources."""
        # Create Claude config
        claude_file = tmp_path / "claude.json"
        claude_file.write_text(json.dumps({"mcpServers": {"server1": {"command": "cmd1"}}}))

        # Create Cursor config
        cursor_dir = tmp_path / "cursor"
        cursor_dir.mkdir()
        cursor_file = cursor_dir / "mcp.json"
        cursor_file.write_text(json.dumps({"mcpServers": {"server2": {"command": "cmd2"}}}))

        def mock_get_config_path(source):
            if source == "claude_desktop":
                return claude_file
            return cursor_dir

        with patch.object(detector, "get_config_path", side_effect=mock_get_config_path):
            results = detector.detect_all()

        assert len(results) == 2
        assert any(r.source == "claude_desktop" and r.found for r in results)
        assert any(r.source == "cursor" and r.found for r in results)


class TestMergeConfigs:
    """Tests for merge_configs function."""

    def test_merge_no_overlap(self):
        """Test merging configs with no overlapping servers."""
        server1 = ServerInfo(name="server1", source="claude_desktop", command="cmd1")
        server2 = ServerInfo(name="server2", source="cursor", command="cmd2")

        configs = [
            DetectedConfig(
                source="claude_desktop",
                path=Path("/a"),
                servers={"server1": server1},
                server_count=1,
            ),
            DetectedConfig(
                source="cursor",
                path=Path("/b"),
                servers={"server2": server2},
                server_count=1,
            ),
        ]

        merged = merge_configs(configs)

        assert len(merged) == 2
        assert "server1" in merged
        assert "server2" in merged

    def test_merge_with_overlap_claude_wins(self):
        """Test merging configs where Claude Desktop takes precedence."""
        server_claude = ServerInfo(name="shared", source="claude_desktop", command="claude_cmd")
        server_cursor = ServerInfo(name="shared", source="cursor", command="cursor_cmd")

        configs = [
            DetectedConfig(
                source="claude_desktop",
                path=Path("/a"),
                servers={"shared": server_claude},
                server_count=1,
            ),
            DetectedConfig(
                source="cursor",
                path=Path("/b"),
                servers={"shared": server_cursor},
                server_count=1,
            ),
        ]

        merged = merge_configs(configs)

        assert len(merged) == 1
        assert merged["shared"].command == "claude_cmd"
