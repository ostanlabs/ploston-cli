"""Unit tests for ploston init injector module."""

from __future__ import annotations

import json

from ploston_cli.init.injector import (
    SourceConfigInjector,
    inject_ploston_into_config,
    is_already_injected,
)


class TestInjectPlostIntoConfig:
    """Tests for inject_ploston_into_config function."""

    def test_inject_creates_backup(self, tmp_path):
        """Test that injection creates a backup file."""
        config_file = tmp_path / "config.json"
        original_config = {
            "mcpServers": {
                "filesystem": {"command": "npx", "args": ["@mcp/filesystem"]},
                "github": {"command": "npx", "args": ["@mcp/github"]},
            }
        }
        config_file.write_text(json.dumps(original_config))

        backup_path = inject_ploston_into_config(
            config_path=config_file,
            imported_servers=["filesystem", "github"],
            cp_url="http://localhost:8080",
        )

        assert backup_path.exists()
        assert "backup_" in backup_path.name
        # Backup should contain original config
        backup_content = json.loads(backup_path.read_text())
        assert "filesystem" in backup_content["mcpServers"]

    def test_inject_moves_servers_to_imported_section(self, tmp_path):
        """Test that imported servers are moved to _ploston_imported."""
        config_file = tmp_path / "config.json"
        original_config = {
            "mcpServers": {
                "filesystem": {"command": "npx", "args": ["@mcp/filesystem"]},
                "github": {"command": "npx", "args": ["@mcp/github"]},
            }
        }
        config_file.write_text(json.dumps(original_config))

        inject_ploston_into_config(
            config_path=config_file,
            imported_servers=["filesystem", "github"],
            cp_url="http://localhost:8080",
        )

        result = json.loads(config_file.read_text())
        assert "_ploston_imported" in result
        assert "filesystem" in result["_ploston_imported"]
        assert "github" in result["_ploston_imported"]

    def test_inject_adds_ploston_entry(self, tmp_path):
        """Test that injection adds ploston proxy entry."""
        config_file = tmp_path / "config.json"
        original_config = {
            "mcpServers": {
                "filesystem": {"command": "npx", "args": ["@mcp/filesystem"]},
            }
        }
        config_file.write_text(json.dumps(original_config))

        inject_ploston_into_config(
            config_path=config_file,
            imported_servers=["filesystem"],
            cp_url="http://localhost:8080",
        )

        result = json.loads(config_file.read_text())
        assert "ploston" in result["mcpServers"]
        ploston_entry = result["mcpServers"]["ploston"]
        assert ploston_entry["command"] == "npx"
        assert "http://localhost:8080" in ploston_entry["args"]

    def test_inject_removes_imported_servers_from_mcp_servers(self, tmp_path):
        """Test that imported servers are removed from mcpServers."""
        config_file = tmp_path / "config.json"
        original_config = {
            "mcpServers": {
                "filesystem": {"command": "npx", "args": ["@mcp/filesystem"]},
                "github": {"command": "npx", "args": ["@mcp/github"]},
                "keep_me": {"command": "other", "args": []},
            }
        }
        config_file.write_text(json.dumps(original_config))

        inject_ploston_into_config(
            config_path=config_file,
            imported_servers=["filesystem", "github"],
            cp_url="http://localhost:8080",
        )

        result = json.loads(config_file.read_text())
        assert "filesystem" not in result["mcpServers"]
        assert "github" not in result["mcpServers"]
        assert "keep_me" in result["mcpServers"]
        assert "ploston" in result["mcpServers"]

    def test_inject_preserves_non_mcp_config(self, tmp_path):
        """Test that non-MCP config is preserved."""
        config_file = tmp_path / "config.json"
        original_config = {
            "mcpServers": {"filesystem": {"command": "npx"}},
            "otherSetting": "value",
            "nested": {"key": "value"},
        }
        config_file.write_text(json.dumps(original_config))

        inject_ploston_into_config(
            config_path=config_file,
            imported_servers=["filesystem"],
            cp_url="http://localhost:8080",
        )

        result = json.loads(config_file.read_text())
        assert result["otherSetting"] == "value"
        assert result["nested"]["key"] == "value"


class TestSourceConfigInjector:
    """Tests for SourceConfigInjector class."""

    def test_inject_via_class(self, tmp_path):
        """Test injection via class interface."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mcpServers": {"server1": {"command": "cmd"}}}))

        injector = SourceConfigInjector(config_file, cp_url="http://localhost:8080")
        backup_path = injector.inject(["server1"])

        assert backup_path.exists()
        result = json.loads(config_file.read_text())
        assert "ploston" in result["mcpServers"]

    def test_is_injected_property(self, tmp_path):
        """Test is_injected property."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mcpServers": {"server1": {"command": "cmd"}}}))

        injector = SourceConfigInjector(config_file)
        assert not injector.is_injected

        injector.inject(["server1"])
        assert injector.is_injected


class TestIsAlreadyInjected:
    """Tests for is_already_injected function."""

    def test_not_injected(self, tmp_path):
        """Test detection when not injected."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mcpServers": {"server1": {"command": "cmd"}}}))

        assert not is_already_injected(config_file)

    def test_already_injected(self, tmp_path):
        """Test detection when already injected."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mcpServers": {"ploston": {"command": "npx"}}}))

        assert is_already_injected(config_file)

    def test_nonexistent_file(self, tmp_path):
        """Test with nonexistent file."""
        config_file = tmp_path / "nonexistent.json"
        assert not is_already_injected(config_file)
