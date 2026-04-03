"""Unit tests for ploston init injector module.

Tests cover the multi-bridge inject pattern per INIT_IMPORT_INJECT_AMENDMENT.md (DEC-141).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ploston_cli.init.injector import (
    SourceConfigInjector,
    _is_ploston_bridge_entry,
    default_runner_name,
    inject_ploston_into_config,
    is_already_injected,
    restore_config_from_imported,
    sanitise_runner_name,
)

# The injector resolves the absolute path to ``ploston`` via shutil.which
# so that GUI apps (Claude Desktop, Cursor) can find the binary.  In tests
# we mock this to a fixed path so assertions are deterministic.
MOCK_PLOSTON_PATH = "/usr/local/bin/ploston"


@pytest.fixture(autouse=True)
def _mock_ploston_which():
    """Mock shutil.which('ploston') for all tests in this module."""
    with patch("ploston_cli.init.injector.shutil.which", return_value=MOCK_PLOSTON_PATH):
        yield


class TestInjectPlostIntoConfig:
    """Tests for inject_ploston_into_config function."""

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
            cp_url="http://localhost:8022",
        )

        result = json.loads(config_file.read_text())
        assert "_ploston_imported" in result
        assert "filesystem" in result["_ploston_imported"]
        assert "github" in result["_ploston_imported"]

    def test_inject_adds_ploston_entry(self, tmp_path):
        """Test that injection adds ploston workflows entry and per-server bridge entries."""
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
            cp_url="http://localhost:8022",
        )

        result = json.loads(config_file.read_text())
        # Workflows entry (tag-based)
        assert "ploston" in result["mcpServers"]
        ploston_entry = result["mcpServers"]["ploston"]
        assert ploston_entry["command"] == MOCK_PLOSTON_PATH
        assert "--tags" in ploston_entry["args"]
        assert "kind:workflow" in ploston_entry["args"]
        assert "http://localhost:8022" in ploston_entry["args"]
        # Authoring entry (tag-based)
        assert "ploston-authoring" in result["mcpServers"]
        auth_entry = result["mcpServers"]["ploston-authoring"]
        assert auth_entry["command"] == MOCK_PLOSTON_PATH
        assert "--tags" in auth_entry["args"]
        assert "kind:workflow_mgmt" in auth_entry["args"]
        # Per-server bridge entry replaces original
        assert "filesystem" in result["mcpServers"]
        fs_entry = result["mcpServers"]["filesystem"]
        assert fs_entry["command"] == MOCK_PLOSTON_PATH
        assert "--expose" in fs_entry["args"]
        assert "filesystem" in fs_entry["args"]

    def test_inject_replaces_imported_servers_with_bridge_entries(self, tmp_path):
        """Test that imported servers are replaced with bridge entries, non-imported preserved."""
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
            cp_url="http://localhost:8022",
        )

        result = json.loads(config_file.read_text())
        # Imported servers replaced with bridge entries (same keys, new values)
        assert "filesystem" in result["mcpServers"]
        assert result["mcpServers"]["filesystem"]["command"] == MOCK_PLOSTON_PATH
        assert "github" in result["mcpServers"]
        assert result["mcpServers"]["github"]["command"] == MOCK_PLOSTON_PATH
        # Non-imported server preserved unchanged
        assert "keep_me" in result["mcpServers"]
        assert result["mcpServers"]["keep_me"]["command"] == "other"
        # Workflows entry added
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
            cp_url="http://localhost:8022",
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

        injector = SourceConfigInjector(config_file, cp_url="http://localhost:8022")
        injector.inject(["server1"])

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


class TestBridgeEntryGeneration:
    """Tests for per-server bridge entry generation (DEC-141 §12 new tests)."""

    def _make_config(self, tmp_path, servers: dict) -> tuple:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mcpServers": servers}))
        return config_file

    def test_one_bridge_entry_per_selected_server(self, tmp_path):
        """Each selected server gets its own bridge entry with --expose <name> --runner <runner>."""
        config_file = self._make_config(
            tmp_path,
            {
                "filesystem": {"command": "npx", "args": ["@mcp/filesystem"]},
                "github": {"command": "npx", "args": ["@mcp/github"]},
                "slack": {"command": "npx", "args": ["@mcp/slack"]},
            },
        )

        inject_ploston_into_config(
            config_file,
            ["filesystem", "github", "slack"],
            cp_url="http://localhost:8082",
            runner_name="marc-macbook",
        )

        result = json.loads(config_file.read_text())
        for name in ["filesystem", "github", "slack"]:
            entry = result["mcpServers"][name]
            assert entry["command"] == MOCK_PLOSTON_PATH
            assert entry["args"] == [
                "bridge",
                "--url",
                "http://localhost:8082",
                "--expose",
                name,
                "--runner",
                "marc-macbook",
            ]

    def test_bridge_args_contain_correct_url(self, tmp_path):
        """--url in bridge args matches the cp_url parameter."""
        config_file = self._make_config(
            tmp_path,
            {
                "fs": {"command": "npx", "args": []},
            },
        )
        inject_ploston_into_config(
            config_file,
            ["fs"],
            cp_url="http://custom:9999",
            runner_name="r1",
        )
        result = json.loads(config_file.read_text())
        assert "http://custom:9999" in result["mcpServers"]["fs"]["args"]

    def test_runner_present_in_per_server_entries(self, tmp_path):
        """Per-server bridge entries include --runner <name>."""
        config_file = self._make_config(
            tmp_path,
            {
                "fs": {"command": "npx", "args": []},
            },
        )
        inject_ploston_into_config(
            config_file,
            ["fs"],
            cp_url="http://localhost:8022",
            runner_name="my-runner",
        )
        result = json.loads(config_file.read_text())
        args = result["mcpServers"]["fs"]["args"]
        idx = args.index("--runner")
        assert args[idx + 1] == "my-runner"

    def test_runner_absent_in_workflows_entry(self, tmp_path):
        """The ploston workflows entry has no --runner arg (uses --tags)."""
        config_file = self._make_config(
            tmp_path,
            {
                "fs": {"command": "npx", "args": []},
            },
        )
        inject_ploston_into_config(
            config_file,
            ["fs"],
            cp_url="http://localhost:8022",
            runner_name="my-runner",
        )
        result = json.loads(config_file.read_text())
        wf_args = result["mcpServers"]["ploston"]["args"]
        assert "--runner" not in wf_args
        assert "--tags" in wf_args
        assert "kind:workflow" in wf_args
        # Authoring entry also has no --runner
        auth_args = result["mcpServers"]["ploston-authoring"]["args"]
        assert "--runner" not in auth_args
        assert "kind:workflow_mgmt" in auth_args

    def test_original_keys_preserved_as_entry_names(self, tmp_path):
        """Bridge entries use the same key name as the original server."""
        config_file = self._make_config(
            tmp_path,
            {
                "my-custom-server": {"command": "node", "args": ["server.js"]},
            },
        )
        inject_ploston_into_config(
            config_file,
            ["my-custom-server"],
            cp_url="http://localhost:8022",
        )
        result = json.loads(config_file.read_text())
        assert "my-custom-server" in result["mcpServers"]
        assert result["mcpServers"]["my-custom-server"]["command"] == MOCK_PLOSTON_PATH

    def test_ploston_imported_has_backup_of_originals(self, tmp_path):
        """_ploston_imported preserves original npx-based entries."""
        original_fs = {"command": "npx", "args": ["@mcp/filesystem", "/Users/marc"]}
        original_gh = {
            "command": "npx",
            "args": ["@mcp/github"],
            "env": {"GITHUB_TOKEN": "ghp_xxx"},
        }
        config_file = self._make_config(
            tmp_path,
            {
                "filesystem": original_fs,
                "github": original_gh,
            },
        )
        inject_ploston_into_config(
            config_file,
            ["filesystem", "github"],
            cp_url="http://localhost:8022",
        )
        result = json.loads(config_file.read_text())
        imported = result["_ploston_imported"]
        assert imported["filesystem"] == original_fs
        assert imported["github"] == original_gh
        assert "_comment" in imported

    def test_runner_name_override_used(self, tmp_path):
        """Provided --runner-name appears in bridge args instead of hostname."""
        config_file = self._make_config(
            tmp_path,
            {
                "fs": {"command": "npx", "args": []},
            },
        )
        inject_ploston_into_config(
            config_file,
            ["fs"],
            cp_url="http://localhost:8022",
            runner_name="custom-name",
        )
        result = json.loads(config_file.read_text())
        assert "custom-name" in result["mcpServers"]["fs"]["args"]

    def test_partial_selection_preserves_non_selected(self, tmp_path):
        """Only selected servers become bridge entries; non-selected are preserved unchanged."""
        config_file = self._make_config(
            tmp_path,
            {
                "filesystem": {"command": "npx", "args": ["@mcp/filesystem"]},
                "github": {"command": "npx", "args": ["@mcp/github"]},
                "keep_me": {"command": "other", "args": ["--flag"]},
            },
        )
        inject_ploston_into_config(
            config_file,
            ["filesystem"],  # only filesystem selected
            cp_url="http://localhost:8022",
            runner_name="r1",
        )
        result = json.loads(config_file.read_text())
        # filesystem → bridge entry
        assert result["mcpServers"]["filesystem"]["command"] == MOCK_PLOSTON_PATH
        # github NOT selected → preserved unchanged
        assert result["mcpServers"]["github"]["command"] == "npx"
        # keep_me → preserved unchanged
        assert result["mcpServers"]["keep_me"]["command"] == "other"
        # Only filesystem in backup
        assert "filesystem" in result["_ploston_imported"]
        assert "github" not in result["_ploston_imported"]
        assert "keep_me" not in result["_ploston_imported"]

    def test_incremental_import_merges_ploston_imported(self, tmp_path):
        """Importing 3 servers then adding a 4th preserves all 4 originals in _ploston_imported."""
        original_fs = {"command": "npx", "args": ["@mcp/filesystem"]}
        original_gh = {"command": "npx", "args": ["@mcp/github"]}
        original_obs = {"command": "npx", "args": ["@mcp/obsidian"]}
        original_grafana = {"command": "npx", "args": ["@mcp/grafana"]}

        config_file = self._make_config(
            tmp_path,
            {
                "filesystem": original_fs,
                "github": original_gh,
                "obsidian": original_obs,
                "grafana": original_grafana,
            },
        )

        # First import: 3 out of 4
        inject_ploston_into_config(
            config_file,
            ["filesystem", "github", "obsidian"],
            cp_url="http://localhost:8022",
            runner_name="r1",
        )
        result = json.loads(config_file.read_text())
        assert "filesystem" in result["_ploston_imported"]
        assert "github" in result["_ploston_imported"]
        assert "obsidian" in result["_ploston_imported"]
        assert "grafana" not in result["_ploston_imported"]
        # grafana should still be in active mcpServers (not imported)
        assert result["mcpServers"]["grafana"] == original_grafana

        # Second import: add the 4th server
        inject_ploston_into_config(
            config_file,
            ["grafana"],
            cp_url="http://localhost:8022",
            runner_name="r1",
        )
        result = json.loads(config_file.read_text())
        imported = result["_ploston_imported"]

        # All 4 originals must be preserved
        assert imported["filesystem"] == original_fs
        assert imported["github"] == original_gh
        assert imported["obsidian"] == original_obs
        assert imported["grafana"] == original_grafana

        # All 4 should have bridge entries in mcpServers
        for name in ["filesystem", "github", "obsidian", "grafana"]:
            assert result["mcpServers"][name]["command"] == MOCK_PLOSTON_PATH

    def test_incremental_import_preserves_earliest_original(self, tmp_path):
        """Re-importing a server that was already imported does not overwrite its original backup."""
        original_fs = {"command": "npx", "args": ["@mcp/filesystem", "/original"]}

        config_file = self._make_config(
            tmp_path,
            {"filesystem": original_fs},
        )

        # First import
        inject_ploston_into_config(
            config_file,
            ["filesystem"],
            cp_url="http://localhost:8022",
        )
        result = json.loads(config_file.read_text())
        assert result["_ploston_imported"]["filesystem"] == original_fs

        # Second import of the same server (now it's a bridge entry in mcpServers)
        inject_ploston_into_config(
            config_file,
            ["filesystem"],
            cp_url="http://localhost:8022",
        )
        result = json.loads(config_file.read_text())
        # The original npx definition should still be preserved, not the bridge entry
        assert result["_ploston_imported"]["filesystem"] == original_fs


class TestEdgeCases:
    """Tests for edge cases E-16, E-17, E-18."""

    def _make_config(self, tmp_path, servers: dict) -> tuple:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mcpServers": servers}))
        return config_file

    def test_e16_ploston_key_collision(self, tmp_path):
        """E-16: Server named 'ploston' is backed up as 'ploston-original'."""
        config_file = self._make_config(
            tmp_path,
            {
                "ploston": {"command": "npx", "args": ["@user/ploston-server"]},
                "other": {"command": "npx", "args": ["@mcp/other"]},
            },
        )
        inject_ploston_into_config(
            config_file,
            ["ploston", "other"],
            cp_url="http://localhost:8022",
            runner_name="r1",
        )
        result = json.loads(config_file.read_text())
        # Workflows entry takes the 'ploston' key (tag-based)
        assert "kind:workflow" in result["mcpServers"]["ploston"]["args"]
        # Original backed up as 'ploston-original'
        assert "ploston-original" in result["_ploston_imported"]
        assert result["_ploston_imported"]["ploston-original"]["command"] == "npx"
        # 'other' gets a bridge entry
        assert result["mcpServers"]["other"]["command"] == MOCK_PLOSTON_PATH

    def test_e17_invalid_chars_in_runner_name(self, tmp_path):
        """E-17: Invalid characters in --runner-name are sanitised."""
        config_file = self._make_config(
            tmp_path,
            {
                "fs": {"command": "npx", "args": []},
            },
        )
        inject_ploston_into_config(
            config_file,
            ["fs"],
            cp_url="http://localhost:8022",
            runner_name="My Machine!@#",
        )
        result = json.loads(config_file.read_text())
        args = result["mcpServers"]["fs"]["args"]
        runner_idx = args.index("--runner")
        runner_val = args[runner_idx + 1]
        # Should be lowercase, alphanumeric + hyphens only
        assert runner_val == "my-machine---"

    def test_e18_no_runner_needed_cp_native(self, tmp_path):
        """E-18: Empty string runner_name omits --runner from all entries."""
        config_file = self._make_config(
            tmp_path,
            {
                "fs": {"command": "npx", "args": []},
            },
        )
        inject_ploston_into_config(
            config_file,
            ["fs"],
            cp_url="http://localhost:8022",
            runner_name="",  # E-18 signal
        )
        result = json.loads(config_file.read_text())
        # Per-server entry should NOT have --runner
        assert "--runner" not in result["mcpServers"]["fs"]["args"]
        # Workflows entry also no --runner
        assert "--runner" not in result["mcpServers"]["ploston"]["args"]


class TestDefaultRunnerName:
    """Tests for default_runner_name() and sanitise_runner_name()."""

    def test_default_runner_name_returns_lowercase(self):
        """default_runner_name() returns lowercase hostname."""
        with patch("ploston_cli.init.injector.socket.gethostname", return_value="MyMachine"):
            name = default_runner_name()
        assert name == "mymachine"

    def test_default_runner_name_replaces_invalid_chars(self):
        """Invalid characters are replaced with hyphens."""
        with patch("ploston_cli.init.injector.socket.gethostname", return_value="my.machine_name"):
            name = default_runner_name()
        assert name == "my-machine-name"

    def test_default_runner_name_max_32_chars(self):
        """Runner name is truncated to 32 characters."""
        with patch("ploston_cli.init.injector.socket.gethostname", return_value="a" * 50):
            name = default_runner_name()
        assert len(name) == 32

    def test_sanitise_runner_name_lowercases(self):
        """sanitise_runner_name lowercases input."""
        assert sanitise_runner_name("MyRunner", warn=False) == "myrunner"

    def test_sanitise_runner_name_replaces_special_chars(self):
        """sanitise_runner_name replaces non-alphanumeric/hyphen chars."""
        assert sanitise_runner_name("my_runner.v2!", warn=False) == "my-runner-v2-"

    def test_sanitise_runner_name_truncates(self):
        """sanitise_runner_name truncates to 32 chars."""
        result = sanitise_runner_name("a" * 50, warn=False)
        assert len(result) == 32


class TestSourceConfigInjectorWithRunnerName:
    """Tests for SourceConfigInjector.inject() with runner_name parameter."""

    def test_inject_via_class_with_runner_name(self, tmp_path):
        """SourceConfigInjector.inject() passes runner_name through."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"mcpServers": {"server1": {"command": "cmd"}}}))

        injector = SourceConfigInjector(config_file, cp_url="http://localhost:8022")
        injector.inject(["server1"], runner_name="test-runner")

        result = json.loads(config_file.read_text())
        args = result["mcpServers"]["server1"]["args"]
        assert "--runner" in args
        runner_idx = args.index("--runner")
        assert args[runner_idx + 1] == "test-runner"


class TestRestoreConfigFromImported:
    """Tests for restore_config_from_imported — inline rollback from _ploston_imported."""

    def test_restores_original_servers(self, tmp_path):
        """Imported servers are moved back into mcpServers."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "serverA": {
                            "command": MOCK_PLOSTON_PATH,
                            "args": [
                                "bridge",
                                "--url",
                                "http://localhost:8022",
                                "--expose",
                                "serverA",
                            ],
                        },
                        "ploston": {
                            "command": MOCK_PLOSTON_PATH,
                            "args": [
                                "bridge",
                                "--url",
                                "http://localhost:8022",
                                "--tags",
                                "kind:workflow",
                            ],
                        },
                    },
                    "_ploston_imported": {
                        "_comment": "Original server definitions",
                        "serverA": {"command": "node", "args": ["serverA.js"]},
                    },
                }
            )
        )

        assert restore_config_from_imported(config_file) is True

        result = json.loads(config_file.read_text())
        assert "serverA" in result["mcpServers"]
        assert result["mcpServers"]["serverA"]["command"] == "node"
        assert "ploston" not in result["mcpServers"]
        assert "_ploston_imported" not in result

    def test_restores_multiple_servers(self, tmp_path):
        """All backed-up servers are restored, all bridges removed."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "a": {"command": MOCK_PLOSTON_PATH, "args": ["bridge", "--expose", "a"]},
                        "b": {"command": MOCK_PLOSTON_PATH, "args": ["bridge", "--expose", "b"]},
                        "ploston": {
                            "command": MOCK_PLOSTON_PATH,
                            "args": ["bridge", "--tags", "kind:workflow"],
                        },
                        "ploston-authoring": {
                            "command": MOCK_PLOSTON_PATH,
                            "args": ["bridge", "--tags", "kind:workflow_mgmt"],
                        },
                        "unmanaged": {"command": "node", "args": ["other.js"]},
                    },
                    "_ploston_imported": {
                        "_comment": "originals",
                        "a": {"command": "node", "args": ["a.js"]},
                        "b": {"command": "python", "args": ["b.py"]},
                    },
                }
            )
        )

        assert restore_config_from_imported(config_file) is True

        result = json.loads(config_file.read_text())
        assert result["mcpServers"]["a"]["command"] == "node"
        assert result["mcpServers"]["b"]["command"] == "python"
        assert result["mcpServers"]["unmanaged"]["command"] == "node"
        assert "ploston" not in result["mcpServers"]
        assert "ploston-authoring" not in result["mcpServers"]

    def test_ploston_original_renamed_back(self, tmp_path):
        """E-16: 'ploston-original' is restored as 'ploston'."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "ploston": {
                            "command": MOCK_PLOSTON_PATH,
                            "args": ["bridge", "--tags", "kind:workflow"],
                        },
                    },
                    "_ploston_imported": {
                        "ploston-original": {"command": "node", "args": ["ploston-server.js"]},
                    },
                }
            )
        )

        assert restore_config_from_imported(config_file) is True

        result = json.loads(config_file.read_text())
        assert result["mcpServers"]["ploston"]["command"] == "node"
        assert "ploston-original" not in result["mcpServers"]

    def test_returns_false_when_no_imported_section(self, tmp_path):
        """Returns False when _ploston_imported doesn't exist."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {"ploston": {"command": MOCK_PLOSTON_PATH, "args": ["bridge"]}},
                }
            )
        )

        assert restore_config_from_imported(config_file) is False

    def test_returns_false_for_missing_file(self, tmp_path):
        """Returns False when config file doesn't exist."""
        assert restore_config_from_imported(tmp_path / "nope.json") is False


class TestIsPlostBridgeEntry:
    """Tests for _is_ploston_bridge_entry helper."""

    def test_bridge_entry(self):
        assert _is_ploston_bridge_entry(
            {"command": "ploston", "args": ["bridge", "--url", "http://localhost"]}
        )

    def test_non_bridge_entry(self):
        assert not _is_ploston_bridge_entry({"command": "node", "args": ["server.js"]})

    def test_empty_dict(self):
        assert not _is_ploston_bridge_entry({})

    def test_non_dict(self):
        assert not _is_ploston_bridge_entry("not a dict")
