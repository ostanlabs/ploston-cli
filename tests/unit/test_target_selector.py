"""Tests for TargetSelector (S-311, T-1002).

Covers Option B pre-check policy, skip-when-0-or-1 behaviour,
non-interactive mode, and --inject-target bypass.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ploston_cli.init.detector import DetectedConfig, ServerInfo
from ploston_cli.init.target_selector import select_targets


def _make_detected(
    source: str, found: bool = True, servers: dict | None = None, path: str = "/tmp/cfg.json"
) -> DetectedConfig:
    srv_map = {}
    if servers:
        for name, cmd in servers.items():
            srv_map[name] = ServerInfo(
                name=name,
                source=source,
                command=cmd,
                args=[],
                env={},
                transport="stdio",
                url=None,
                env_vars_required=[],
                env_vars_available={},
                raw_config={"command": cmd},
            )
    return DetectedConfig(
        source=source,
        path=Path(path) if found else Path("/nonexistent"),
        servers=srv_map,
        server_count=len(srv_map),
        error=None if found else "Config not found",
    )


class TestTargetSelectorPreCheckPolicy:
    """T-1002: Option B pre-check policy."""

    def test_explicit_inject_targets_bypass_picker(self):
        detected = [_make_detected("cursor", servers={"gh": "npx"})]
        result = select_targets(
            detected_configs=detected,
            selected_server_names=["gh"],
            inject_targets=["cursor"],
        )
        assert result == ["cursor"]

    def test_non_interactive_returns_contributors_only(self):
        """Non-interactive mode: only targets that contributed selected servers."""
        detected = [
            _make_detected("claude_desktop", servers={"gh": "npx"}),
            _make_detected("cursor", servers={"other": "cmd"}),
        ]
        result = select_targets(
            detected_configs=detected,
            selected_server_names=["gh"],
            non_interactive=True,
        )
        assert result == ["claude_desktop"]

    def test_skips_prompt_with_zero_viable(self):
        detected = [_make_detected("cursor", found=False)]
        result = select_targets(
            detected_configs=detected,
            selected_server_names=["gh"],
        )
        assert result == []

    def test_skips_prompt_with_one_viable(self):
        detected = [
            _make_detected("cursor", servers={"gh": "npx"}),
            _make_detected("windsurf", found=False),
        ]
        result = select_targets(
            detected_configs=detected,
            selected_server_names=["gh"],
        )
        assert result == ["cursor"]

    def test_interactive_picker_called_with_two_viable(self):
        detected = [
            _make_detected("claude_desktop", servers={"gh": "npx"}),
            _make_detected("cursor", servers={"other": "cmd"}),
        ]
        # Mock questionary.checkbox to simulate user selecting both
        with patch("ploston_cli.init.target_selector.questionary") as mock_q:
            mock_q.Choice = type(
                "Choice", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}
            )
            mock_q.checkbox.return_value.ask.return_value = ["claude_desktop", "cursor"]
            result = select_targets(
                detected_configs=detected,
                selected_server_names=["gh"],
            )
        assert set(result) == {"claude_desktop", "cursor"}
        mock_q.checkbox.assert_called_once()

    def test_contributor_is_pre_checked_non_contributor_is_not(self):
        detected = [
            _make_detected("claude_desktop", servers={"gh": "npx"}),
            _make_detected("cursor", servers={"other": "cmd"}),
        ]
        choices_captured = []

        with patch("ploston_cli.init.target_selector.questionary") as mock_q:
            original_choice = type(
                "Choice", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}
            )
            mock_q.Choice = original_choice
            mock_q.checkbox.return_value.ask.return_value = ["claude_desktop"]

            def capture_checkbox(prompt, choices):
                choices_captured.extend(choices)
                return mock_q.checkbox.return_value

            mock_q.checkbox.side_effect = capture_checkbox

            select_targets(
                detected_configs=detected,
                selected_server_names=["gh"],
            )

        # Claude Desktop contributed "gh" → pre-checked
        claude_choice = next(c for c in choices_captured if c.value == "claude_desktop")
        assert claude_choice.checked is True

        # Cursor did NOT contribute "gh" → unchecked
        cursor_choice = next(c for c in choices_captured if c.value == "cursor")
        assert cursor_choice.checked is False

    def test_user_ctrl_c_returns_empty(self):
        detected = [
            _make_detected("claude_desktop", servers={"gh": "npx"}),
            _make_detected("cursor", servers={"other": "cmd"}),
        ]
        with patch("ploston_cli.init.target_selector.questionary") as mock_q:
            mock_q.Choice = type(
                "Choice", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}
            )
            mock_q.checkbox.return_value.ask.return_value = None
            result = select_targets(
                detected_configs=detected,
                selected_server_names=["gh"],
            )
        assert result == []
