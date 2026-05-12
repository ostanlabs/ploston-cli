"""Adapter-level backup contract tests (§6.1 T-1006).

These verify that the Layer-2 file backup integrates correctly with each
ConfigAdapter shape — i.e. that inject_via_target creates a backup and that
the backup content can restore the original config verbatim.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ploston_cli.init.backup import find_latest_backup, restore_from_backup

MOCK_PLOSTON_PATH = "/usr/local/bin/ploston"


@pytest.fixture(autouse=True)
def _mock_ploston_which():
    with patch("ploston_cli.init.injector.shutil.which", return_value=MOCK_PLOSTON_PATH):
        yield


class TestMcpServersAdapterBackupRoundTrip:
    """Backup → inject → restore round-trip for mcpServers shape."""

    def test_mcp_servers_adapter_backup_round_trip(self, tmp_path):
        """Layer-2 backup preserves the original mcpServers config verbatim.

        Flow: create config → inject (backup created automatically) → verify
        backup matches original → restore from backup → verify config matches original.
        """
        from ploston_cli.init.injector import inject_via_target

        config_file = tmp_path / "mcp.json"
        original = {
            "mcpServers": {
                "github": {"command": "npx", "args": ["@mcp/github"]},
                "filesystem": {"command": "npx", "args": ["@mcp/filesystem"]},
            },
            "theme": "dark",
        }
        original_text = json.dumps(original, indent=2)
        config_file.write_text(original_text, encoding="utf-8")

        # Inject — this should create a Layer-2 backup automatically
        inject_via_target(
            source_id="claude_desktop",
            config_path=config_file,
            imported_servers=["github"],
            cp_url="http://localhost:8022",
            runner_name="test-runner",
            no_backup_file=False,
        )

        # Verify backup exists and matches original content
        backup = find_latest_backup(config_file)
        assert backup is not None, "Layer-2 backup should have been created"
        assert backup.read_text(encoding="utf-8") == original_text

        # Config should now be modified (bridge entries)
        modified = json.loads(config_file.read_text(encoding="utf-8"))
        assert modified["mcpServers"]["github"]["command"] == MOCK_PLOSTON_PATH

        # Restore from backup
        assert restore_from_backup(config_file) is True
        restored = json.loads(config_file.read_text(encoding="utf-8"))
        assert restored == original


class TestMicrosoftServersAdapterBackupPreservesInputs:
    """Backup round-trip for Microsoft servers shape with inputs: array."""

    def test_microsoft_servers_adapter_backup_preserves_inputs(self, tmp_path):
        """Layer-2 backup preserves the inputs: array in Microsoft-shape configs.

        This is the critical contract: the backup must preserve the entire file
        including the inputs array, so restore-from-backup returns the config to
        its exact pre-injection state.
        """
        from ploston_cli.init.injector import inject_via_target

        config_file = tmp_path / "mcp.json"
        original = {
            "servers": {"gh": {"type": "stdio", "command": "npx", "args": ["@mcp/github"]}},
            "inputs": [{"id": "github-token", "type": "promptString", "description": "GitHub PAT"}],
        }
        original_text = json.dumps(original, indent=2)
        config_file.write_text(original_text, encoding="utf-8")

        # Inject via Microsoft-shape target — backup created automatically
        inject_via_target(
            source_id="vscode_copilot_workspace",
            config_path=config_file,
            imported_servers=["gh"],
            cp_url="http://localhost:8022",
            runner_name="test-runner",
            no_backup_file=False,
        )

        # Verify backup exists and preserves inputs
        backup = find_latest_backup(config_file)
        assert backup is not None, "Layer-2 backup should have been created"
        backup_content = json.loads(backup.read_text(encoding="utf-8"))
        assert backup_content["inputs"] == original["inputs"]
        assert backup_content["servers"]["gh"]["command"] == "npx"  # original command

        # Config should now be modified
        modified = json.loads(config_file.read_text(encoding="utf-8"))
        assert modified["servers"]["gh"]["command"] == MOCK_PLOSTON_PATH

        # Restore from backup — inputs must come back
        assert restore_from_backup(config_file) is True
        restored = json.loads(config_file.read_text(encoding="utf-8"))
        assert restored == original
        assert restored["inputs"] == original["inputs"]
