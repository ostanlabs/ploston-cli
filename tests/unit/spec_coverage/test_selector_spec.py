"""Specification-driven tests for ploston_cli.init.selector.ServerSelector.

Boundary mocked: questionary.checkbox (the interactive prompt). All the
selection/formatting logic is exercised directly.

Contract:
  - prompt_selection returns selected names; empty input list → [] (no prompt).
  - Cancelling the prompt (questionary returns None) raises KeyboardInterrupt.
  - Servers with all env vars satisfied are pre-checked.
  - select_all returns every server's name.
  - _format_env_status renders ✓/⚠ per required var.
  - display_import_summary pluralises correctly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ploston_cli.init.detector import ServerInfo
from ploston_cli.init.selector import ServerSelector, display_import_summary


def _info(name="srv", **kw) -> ServerInfo:
    return ServerInfo(name=name, source=kw.pop("source", "claude_desktop"), **kw)


@pytest.fixture
def selector() -> ServerSelector:
    return ServerSelector()


class TestPromptSelection:
    async def test_empty_list_returns_empty_without_prompting(self, selector):
        with patch("ploston_cli.init.selector.questionary.checkbox") as q:
            result = await selector.prompt_selection([])
        assert result == []
        q.assert_not_called()

    async def test_returns_selected_names(self, selector):
        infos = [_info("a"), _info("b")]
        with patch("ploston_cli.init.selector.questionary.checkbox") as q:
            q.return_value.ask_async = AsyncMock(return_value=["a"])
            result = await selector.prompt_selection(infos)
        assert result == ["a"]

    async def test_cancel_raises_keyboardinterrupt(self, selector):
        """questionary returning None means Ctrl+C → KeyboardInterrupt."""
        infos = [_info("a")]
        with patch("ploston_cli.init.selector.questionary.checkbox") as q:
            q.return_value.ask_async = AsyncMock(return_value=None)
            with pytest.raises(KeyboardInterrupt):
                await selector.prompt_selection(infos)

    async def test_servers_with_all_env_set_are_prechecked(self, selector):
        """A server whose required env vars are all available is pre-checked."""
        ready = _info(
            "ready",
            env_vars_required=["TOKEN"],
            env_vars_available={"TOKEN": True},
        )
        not_ready = _info(
            "blocked",
            env_vars_required=["KEY"],
            env_vars_available={"KEY": False},
        )
        captured = {}

        def fake_checkbox(_msg, choices, style):
            captured["choices"] = choices
            m = MagicMock()
            m.ask_async = AsyncMock(return_value=[])
            return m

        with patch("ploston_cli.init.selector.questionary.checkbox", side_effect=fake_checkbox):
            await selector.prompt_selection([ready, not_ready])

        checked = {c.value: c.checked for c in captured["choices"]}
        assert checked["ready"] is True
        assert checked["blocked"] is False


class TestSelectAll:
    def test_returns_all_names(self, selector):
        infos = [_info("a"), _info("b"), _info("c")]
        assert selector.select_all(infos) == ["a", "b", "c"]

    def test_empty(self, selector):
        assert selector.select_all([]) == []


class TestFormatEnvStatus:
    def test_no_required_vars_returns_empty(self, selector):
        assert selector._format_env_status(_info()) == ""

    def test_set_var_shows_checkmark(self, selector):
        info = _info(env_vars_required=["TOKEN"], env_vars_available={"TOKEN": True})
        out = selector._format_env_status(info)
        assert "✓" in out
        assert "TOKEN" in out
        assert "not set" not in out

    def test_unset_var_shows_warning(self, selector):
        info = _info(env_vars_required=["KEY"], env_vars_available={"KEY": False})
        out = selector._format_env_status(info)
        assert "⚠" in out
        assert "KEY (not set)" in out

    def test_missing_availability_treated_as_unset(self, selector):
        """Required var with no availability entry defaults to not-set."""
        info = _info(env_vars_required=["KEY"], env_vars_available={})
        out = selector._format_env_status(info)
        assert "not set" in out

    def test_multiple_vars_joined(self, selector):
        info = _info(
            env_vars_required=["A", "B"],
            env_vars_available={"A": True, "B": False},
        )
        out = selector._format_env_status(info)
        assert " | " in out


class TestFormatServerChoice:
    def test_includes_name_and_command(self, selector):
        info = _info("github", command="npx", args=["@mcp/github"])
        title = selector._format_server_choice(info)
        assert "github" in title
        assert "npx" in title

    def test_includes_env_status_line_when_present(self, selector):
        info = _info(
            "gh",
            command="npx",
            env_vars_required=["TOKEN"],
            env_vars_available={"TOKEN": False},
        )
        title = selector._format_server_choice(info)
        assert "\n" in title  # multi-line: command line + env status line
        assert "not set" in title


class TestDisplayImportSummary:
    def test_zero(self, capsys):
        display_import_summary([])
        assert "No servers selected" in capsys.readouterr().out

    def test_singular(self, capsys):
        display_import_summary(["a"], runner_name="local")
        out = capsys.readouterr().out
        assert "1 server selected" in out
        assert "local" in out

    def test_plural(self, capsys):
        display_import_summary(["a", "b"], runner_name="box")
        out = capsys.readouterr().out
        assert "2 servers selected" in out
        assert "box" in out
