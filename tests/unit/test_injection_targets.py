"""Tests for InjectionTarget plugin system (S-308, S-309, S-310).

Covers TARGET_REGISTRY dispatch, per-target detect/inject/rollback round-trips,
and Gemini CLI sibling-key preservation.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ploston_cli.init.injection_targets.adapters import McpServersAdapter, MicrosoftServersAdapter
from ploston_cli.init.injection_targets.base import InjectionTarget, _current_platform
from ploston_cli.init.injection_targets.composite import CompositeAdapter
from ploston_cli.init.injection_targets.formats import TomlFormat
from ploston_cli.init.injection_targets.registry import TARGET_REGISTRY
from ploston_cli.init.injection_targets.shapes import (
    ContextServersShape,
    McpServersShape,
    MicrosoftServersShape,
)

# Mock ploston path for deterministic assertions
MOCK_PLOSTON_PATH = "/usr/local/bin/ploston"


@pytest.fixture(autouse=True)
def _mock_ploston_which():
    with patch("ploston_cli.init.injector.shutil.which", return_value=MOCK_PLOSTON_PATH):
        yield


class TestTargetRegistryDispatchRoundTrip:
    """T-991: TARGET_REGISTRY dispatch round-trip."""

    def test_registry_has_all_expected_targets(self):
        expected = {
            "claude_desktop",
            "cursor",
            "cursor_project",
            "claude_code_global",
            "claude_code_project",
            "windsurf",
            "gemini_cli_global",
            "gemini_cli_project",
            "cline",
            "vscode_copilot_workspace",
            "vscode_copilot_user",
            "visual_studio_user",
            "codex_global",
            "codex_project",
            "zed_user",
            "zed_project",
        }
        assert set(TARGET_REGISTRY.keys()) == expected

    def test_all_targets_are_injection_target_instances(self):
        for sid, target in TARGET_REGISTRY.items():
            assert isinstance(target, InjectionTarget), f"{sid} is not an InjectionTarget"
            assert target.source_id == sid

    def test_all_targets_have_display_name(self):
        for sid, target in TARGET_REGISTRY.items():
            assert target.display_name, f"{sid} has empty display_name"

    def test_all_targets_have_adapter(self):
        for sid, target in TARGET_REGISTRY.items():
            assert target.adapter is not None, f"{sid} has no adapter"

    def test_all_targets_have_scope(self):
        for sid, target in TARGET_REGISTRY.items():
            assert target.scope in ("global", "project"), f"{sid} has invalid scope: {target.scope}"

    def test_inject_and_rollback_round_trip_mcpservers(self, tmp_path):
        """Inject into a mcpServers-shape config and verify structure."""
        from ploston_cli.init.injector import inject_via_target, restore_config_from_imported

        config_file = tmp_path / "config.json"
        original = {"mcpServers": {"gh": {"command": "npx", "args": ["@mcp/github"]}}}
        config_file.write_text(json.dumps(original))

        inject_via_target(
            source_id="cursor",
            config_path=config_file,
            imported_servers=["gh"],
            cp_url="http://localhost:8022",
            runner_name="test-runner",
        )

        result = json.loads(config_file.read_text())
        assert result["mcpServers"]["gh"]["command"] == MOCK_PLOSTON_PATH
        assert "ploston" in result["mcpServers"]
        assert "ploston-authoring" in result["mcpServers"]
        assert result["_ploston_imported"]["gh"]["command"] == "npx"

        # Rollback
        assert restore_config_from_imported(config_file) is True
        restored = json.loads(config_file.read_text())
        assert restored["mcpServers"]["gh"]["command"] == "npx"
        assert "ploston" not in restored["mcpServers"]
        assert "_ploston_imported" not in restored


class TestPerTargetDetection:
    """One detect test per new Wave 1 target."""

    @pytest.mark.parametrize("source_id", list(TARGET_REGISTRY.keys()))
    def test_detect_returns_path_or_none(self, source_id):
        target = TARGET_REGISTRY[source_id]
        home = Path("/mock/home")
        cwd = Path("/mock/project")
        result = target.detect(home, cwd)
        platform = _current_platform()
        if platform in target.config_path_template:
            assert result is not None, f"{source_id} should return a path on {platform}"
            assert isinstance(result, Path)
        else:
            assert result is None, f"{source_id} should return None on {platform}"


class TestGeminiCLIPreservesUnrelatedKeys:
    """T-994: Non-mcpServers keys in settings.json are preserved on round-trip."""

    def test_gemini_cli_preserves_sibling_keys(self, tmp_path):
        from ploston_cli.init.injector import inject_via_target

        config_file = tmp_path / "settings.json"
        original = {
            "theme": "dark",
            "telemetry": False,
            "mcpServers": {"gh": {"command": "npx", "args": ["@mcp/github"]}},
        }
        config_file.write_text(json.dumps(original))

        inject_via_target(
            source_id="gemini_cli_global",
            config_path=config_file,
            imported_servers=["gh"],
            cp_url="http://localhost:8022",
        )

        result = json.loads(config_file.read_text())
        assert result["theme"] == "dark"
        assert result["telemetry"] is False
        assert "ploston" in result["mcpServers"]


# ---------------------------------------------------------------------------
# S-314 / M-085: Cross-target regression matrix
# ---------------------------------------------------------------------------

_MCP_SERVERS_TARGETS = [
    sid for sid, t in TARGET_REGISTRY.items() if isinstance(t.adapter, McpServersAdapter)
]
_MS_SERVERS_TARGETS = [
    sid for sid, t in TARGET_REGISTRY.items() if isinstance(t.adapter, MicrosoftServersAdapter)
]
_CODEX_TARGETS = [
    sid
    for sid, t in TARGET_REGISTRY.items()
    if isinstance(t.adapter, CompositeAdapter)
    and isinstance(t.adapter.format, TomlFormat)
    and isinstance(t.adapter.shape, McpServersShape)
]
_ZED_TARGETS = [
    sid
    for sid, t in TARGET_REGISTRY.items()
    if isinstance(t.adapter, CompositeAdapter) and isinstance(t.adapter.shape, ContextServersShape)
]


def _seed_config(target_id: str, tmp_path: Path) -> Path:
    """Create a seed config file with a pre-existing server for *target_id*."""
    target = TARGET_REGISTRY[target_id]
    adapter = target.adapter

    # Determine shape and format to produce correct seed content
    shape = adapter.shape if isinstance(adapter, CompositeAdapter) else None
    uses_toml = isinstance(adapter, CompositeAdapter) and isinstance(adapter.format, TomlFormat)

    if isinstance(adapter, MicrosoftServersAdapter) or isinstance(shape, MicrosoftServersShape):
        seed = {
            "servers": {"existing-mcp": {"command": "npx", "args": ["@mcp/test"]}},
            "inputs": [{"type": "promptString", "id": "token", "description": "API token"}],
        }
    elif isinstance(shape, ContextServersShape):
        seed = {"context_servers": {"existing-mcp": {"command": "npx", "args": ["@mcp/test"]}}}
    elif isinstance(shape, McpServersShape) and shape.servers_key != "mcpServers":
        # Codex uses mcp_servers
        seed = {shape.servers_key: {"existing-mcp": {"command": "npx", "args": ["@mcp/test"]}}}
    else:
        seed = {"mcpServers": {"existing-mcp": {"command": "npx", "args": ["@mcp/test"]}}}

    ext = ".toml" if uses_toml else ".json"
    config_file = tmp_path / f"{target_id}{ext}"

    if uses_toml:
        import tomlkit

        config_file.write_text(tomlkit.dumps(seed), encoding="utf-8")
    else:
        config_file.write_text(json.dumps(seed))

    return config_file


class TestCrossTargetRegressionMatrix:
    """S-314: Parametrised inject + verify for every target in TARGET_REGISTRY.

    Checks:
    1. Injection writes ploston + ploston-authoring entries
    2. Original server is backed up in _ploston_imported
    3. Microsoft targets get "type": "stdio" via decorate_server_entry (S-313)
    4. McpServers targets do NOT get "type": "stdio"
    5. Sibling keys (e.g. "inputs") are preserved on round-trip
    """

    @pytest.mark.parametrize("source_id", _MCP_SERVERS_TARGETS)
    def test_mcpservers_inject_round_trip(self, source_id, tmp_path):
        from ploston_cli.init.injector import inject_via_target

        config_file = _seed_config(source_id, tmp_path)
        inject_via_target(
            source_id=source_id,
            config_path=config_file,
            imported_servers=["existing-mcp"],
            cp_url="http://localhost:8022",
            runner_name="test-runner",
        )
        result = json.loads(config_file.read_text())
        servers = result["mcpServers"]

        # Bridge entries exist
        assert "ploston" in servers, f"{source_id}: missing 'ploston' entry"
        assert "ploston-authoring" in servers, f"{source_id}: missing 'ploston-authoring' entry"
        assert "existing-mcp" in servers, f"{source_id}: missing bridged 'existing-mcp' entry"

        # No "type": "stdio" for mcpServers shape
        assert "type" not in servers["ploston"], f"{source_id}: unexpected 'type' key"

        # Backup section
        assert result["_ploston_imported"]["existing-mcp"]["command"] == "npx"

    @pytest.mark.parametrize("source_id", _MS_SERVERS_TARGETS)
    def test_microsoft_inject_round_trip(self, source_id, tmp_path):
        from ploston_cli.init.injector import inject_via_target

        config_file = _seed_config(source_id, tmp_path)
        inject_via_target(
            source_id=source_id,
            config_path=config_file,
            imported_servers=["existing-mcp"],
            cp_url="http://localhost:8022",
            runner_name="test-runner",
        )
        result = json.loads(config_file.read_text())
        servers = result["servers"]

        # Bridge entries exist
        assert "ploston" in servers, f"{source_id}: missing 'ploston' entry"
        assert "ploston-authoring" in servers, f"{source_id}: missing 'ploston-authoring' entry"
        assert "existing-mcp" in servers, f"{source_id}: missing bridged 'existing-mcp' entry"

        # "type": "stdio" required for Microsoft shape (S-313 decorate_server_entry)
        assert servers["ploston"]["type"] == "stdio", f"{source_id}: missing 'type: stdio'"
        assert servers["ploston-authoring"]["type"] == "stdio"
        assert servers["existing-mcp"]["type"] == "stdio"

        # Backup section
        assert result["_ploston_imported"]["existing-mcp"]["command"] == "npx"

        # Sibling keys preserved (inputs array)
        assert result.get("inputs") == [
            {"type": "promptString", "id": "token", "description": "API token"}
        ], f"{source_id}: inputs array lost on round-trip"

    @pytest.mark.parametrize("source_id", _CODEX_TARGETS)
    def test_codex_inject_round_trip(self, source_id, tmp_path):
        """Codex (TOML) targets: inject + verify mcp_servers key and backup."""
        import tomlkit

        from ploston_cli.init.injector import inject_via_target

        config_file = _seed_config(source_id, tmp_path)
        inject_via_target(
            source_id=source_id,
            config_path=config_file,
            imported_servers=["existing-mcp"],
            cp_url="http://localhost:8022",
            runner_name="test-runner",
        )
        result = tomlkit.loads(config_file.read_text())
        servers = result["mcp_servers"]

        # Bridge entries exist
        assert "ploston" in servers, f"{source_id}: missing 'ploston' entry"
        assert "ploston-authoring" in servers, f"{source_id}: missing 'ploston-authoring' entry"
        assert "existing-mcp" in servers, f"{source_id}: missing bridged 'existing-mcp' entry"

        # No "type": "stdio" for mcpServers shape
        assert "type" not in dict(servers["ploston"]), f"{source_id}: unexpected 'type' key"

        # Backup section
        assert result["_ploston_imported"]["existing-mcp"]["command"] == "npx"

    @pytest.mark.parametrize("source_id", _ZED_TARGETS)
    def test_zed_inject_round_trip(self, source_id, tmp_path):
        """Zed targets: inject + verify context_servers key and backup."""
        from ploston_cli.init.injector import inject_via_target

        config_file = _seed_config(source_id, tmp_path)
        inject_via_target(
            source_id=source_id,
            config_path=config_file,
            imported_servers=["existing-mcp"],
            cp_url="http://localhost:8022",
            runner_name="test-runner",
        )
        result = json.loads(config_file.read_text())
        servers = result["context_servers"]

        # Bridge entries exist
        assert "ploston" in servers, f"{source_id}: missing 'ploston' entry"
        assert "ploston-authoring" in servers, f"{source_id}: missing 'ploston-authoring' entry"
        assert "existing-mcp" in servers, f"{source_id}: missing bridged 'existing-mcp' entry"

        # No "type": "stdio" for context_servers shape
        assert "type" not in servers["ploston"], f"{source_id}: unexpected 'type' key"

        # Backup section
        assert result["_ploston_imported"]["existing-mcp"]["command"] == "npx"

    @pytest.mark.parametrize("source_id", list(TARGET_REGISTRY.keys()))
    def test_decorate_server_entry_matches_adapter(self, source_id):
        """Verify decorate_server_entry is consistent with adapter type."""
        from ploston_cli.init.injection_targets.adapters import MicrosoftServersAdapter

        target = TARGET_REGISTRY[source_id]
        entry = {"command": "ploston", "args": ["bridge"]}
        decorated = target.adapter.decorate_server_entry(entry)

        if isinstance(target.adapter, MicrosoftServersAdapter):
            assert decorated["type"] == "stdio", f"{source_id}: adapter should add type:stdio"
        else:
            assert "type" not in decorated, f"{source_id}: adapter should not add type"

    @pytest.mark.parametrize("source_id", list(TARGET_REGISTRY.keys()))
    def test_adapter_read_write_round_trip(self, source_id, tmp_path):
        """Adapter read → write → read round-trip preserves structure."""
        config_file = _seed_config(source_id, tmp_path)
        target = TARGET_REGISTRY[source_id]
        adapter = target.adapter

        data1 = adapter.read(config_file)
        adapter.write(config_file, data1)
        data2 = adapter.read(config_file)
        assert data1 == data2, f"{source_id}: adapter round-trip failed"
