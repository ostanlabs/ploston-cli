"""Tests for InjectionTarget plugin system (S-308, S-309, S-310).

Covers TARGET_REGISTRY dispatch, per-target detect/inject/rollback round-trips,
and Gemini CLI sibling-key preservation.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ploston_cli.init.injection_targets.base import InjectionTarget, _current_platform
from ploston_cli.init.injection_targets.registry import TARGET_REGISTRY

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
