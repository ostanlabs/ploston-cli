"""Tests for ConfigAdapter implementations (S-308, S-310).

Covers McpServersAdapter sibling-key preservation and
MicrosoftServersAdapter inputs-array preservation.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ploston_cli.init.injection_targets.adapters import (
    McpServersAdapter,
    MicrosoftServersAdapter,
)

MOCK_PLOSTON_PATH = "/usr/local/bin/ploston"


@pytest.fixture(autouse=True)
def _mock_ploston_which():
    with patch("ploston_cli.init.injector.shutil.which", return_value=MOCK_PLOSTON_PATH):
        yield


class TestMcpServersAdapter:
    """Tests for McpServersAdapter."""

    def test_round_trip_preserves_sibling_keys(self, tmp_path):
        """Non-mcpServers keys are preserved through read → modify → write."""
        adapter = McpServersAdapter()
        config_file = tmp_path / "config.json"
        original = {
            "mcpServers": {"gh": {"command": "npx"}},
            "theme": "dark",
            "nested": {"key": "value"},
        }
        config_file.write_text(json.dumps(original))

        data = adapter.read(config_file)
        servers = adapter.get_servers(data)
        servers["new"] = {"command": "test"}
        data = adapter.set_servers(data, servers)
        adapter.write(config_file, data)

        result = json.loads(config_file.read_text())
        assert result["theme"] == "dark"
        assert result["nested"]["key"] == "value"
        assert "new" in result["mcpServers"]

    def test_backup_section_operations(self, tmp_path):
        adapter = McpServersAdapter()
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mcpServers": {}}))

        data = adapter.read(config_file)
        assert adapter.get_backup_section(data) == {}

        data = adapter.set_backup_section(data, {"gh": {"command": "npx"}})
        assert adapter.get_backup_section(data) == {"gh": {"command": "npx"}}

        data = adapter.strip_backup_section(data)
        assert "_ploston_imported" not in data


class TestMicrosoftServersAdapter:
    """Tests for MicrosoftServersAdapter."""

    def test_preserves_inputs_array(self, tmp_path):
        """The inputs: array is preserved verbatim on round-trip."""
        adapter = MicrosoftServersAdapter()
        config_file = tmp_path / "mcp.json"
        original = {
            "servers": {"gh": {"type": "stdio", "command": "npx", "args": ["@mcp/github"]}},
            "inputs": [{"id": "github-token", "type": "promptString", "description": "GitHub PAT"}],
        }
        config_file.write_text(json.dumps(original))

        data = adapter.read(config_file)
        servers = adapter.get_servers(data)
        servers["new"] = {"type": "stdio", "command": "test"}
        data = adapter.set_servers(data, servers)
        adapter.write(config_file, data)

        result = json.loads(config_file.read_text())
        # inputs preserved verbatim
        assert result["inputs"] == original["inputs"]
        assert "new" in result["servers"]
        assert "gh" in result["servers"]

    def test_microsoft_inject_round_trip(self, tmp_path):
        """inject_via_target with a Microsoft-shape target produces type:stdio entries."""
        from ploston_cli.init.injector import inject_via_target

        config_file = tmp_path / "mcp.json"
        original = {
            "servers": {"gh": {"type": "stdio", "command": "npx", "args": ["@mcp/github"]}},
            "inputs": [{"id": "github-token", "type": "promptString", "description": "GitHub PAT"}],
        }
        config_file.write_text(json.dumps(original))

        inject_via_target(
            source_id="vscode_copilot_workspace",
            config_path=config_file,
            imported_servers=["gh"],
            cp_url="http://localhost:8022",
            runner_name="test-runner",
        )

        result = json.loads(config_file.read_text())
        # Bridge entries have "type": "stdio"
        assert result["servers"]["gh"]["type"] == "stdio"
        assert result["servers"]["gh"]["command"] == MOCK_PLOSTON_PATH
        assert result["servers"]["ploston"]["type"] == "stdio"
        assert result["servers"]["ploston-authoring"]["type"] == "stdio"
        # inputs preserved
        assert result["inputs"] == original["inputs"]
        # Backup section created
        assert result["_ploston_imported"]["gh"]["command"] == "npx"
