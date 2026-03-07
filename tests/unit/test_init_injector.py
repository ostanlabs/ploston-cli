"""Unit tests for ploston init injector module.

Tests cover the multi-bridge inject pattern per INIT_IMPORT_INJECT_AMENDMENT.md (DEC-141).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ploston_cli.init.injector import (
    SourceConfigInjector,
    default_runner_name,
    inject_ploston_into_config,
    is_already_injected,
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
            cp_url="http://localhost:8022",
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
        # Workflows entry
        assert "ploston" in result["mcpServers"]
        ploston_entry = result["mcpServers"]["ploston"]
        assert ploston_entry["command"] == MOCK_PLOSTON_PATH
        assert "--expose" in ploston_entry["args"]
        assert "workflows" in ploston_entry["args"]
        assert "http://localhost:8022" in ploston_entry["args"]
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
        """The ploston workflows entry has no --runner arg."""
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
        assert "workflows" in wf_args

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
        # Workflows entry takes the 'ploston' key
        assert (
            result["mcpServers"]["ploston"]["args"][-1] == "workflows"
            or "workflows" in result["mcpServers"]["ploston"]["args"]
        )
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
