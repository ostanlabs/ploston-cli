"""TARGET_REGISTRY — single source of truth for all injection targets (T-991).

Each target is an InjectionTarget instance keyed by source_id.
Adding a new agent = instantiate + register here.

See: MULTI_AGENT_BOOTSTRAP_EXPANSION_W1_SPEC.md §3.1
"""

from __future__ import annotations

from typing import Any

from .adapters import McpServersAdapter, MicrosoftServersAdapter
from .base import InjectionTarget

# ---------------------------------------------------------------------------
# Shared adapter singletons
# ---------------------------------------------------------------------------

_mcp_adapter = McpServersAdapter()
_ms_adapter = MicrosoftServersAdapter()


# ---------------------------------------------------------------------------
# Target subclasses
# ---------------------------------------------------------------------------


class _ClaudeDesktop(InjectionTarget):
    source_id = "claude_desktop"
    display_name = "Claude Desktop"
    scope = "global"
    adapter = _mcp_adapter
    config_path_template = {
        "darwin": "{home}/Library/Application Support/Claude/claude_desktop_config.json",
        "linux": "{home}/.config/Claude/claude_desktop_config.json",
        "windows": "{home}/AppData/Roaming/Claude/claude_desktop_config.json",
    }


class _CursorGlobal(InjectionTarget):
    source_id = "cursor"
    display_name = "Cursor"
    scope = "global"
    adapter = _mcp_adapter
    config_path_template = {
        "darwin": "{home}/.cursor/mcp.json",
        "linux": "{home}/.cursor/mcp.json",
        "windows": "{home}/.cursor/mcp.json",
    }


class _CursorProject(InjectionTarget):
    source_id = "cursor_project"
    display_name = "Cursor (project)"
    scope = "project"
    adapter = _mcp_adapter
    config_path_template = {
        "darwin": "{cwd}/.cursor/mcp.json",
        "linux": "{cwd}/.cursor/mcp.json",
        "windows": "{cwd}/.cursor/mcp.json",
    }


class _ClaudeCodeGlobal(InjectionTarget):
    source_id = "claude_code_global"
    display_name = "Claude Code (global)"
    scope = "global"
    adapter = _mcp_adapter
    config_path_template = {
        "darwin": "{home}/.claude/settings.json",
        "linux": "{home}/.claude/settings.json",
        "windows": "{home}/.claude/settings.json",
    }


class _ClaudeCodeProject(InjectionTarget):
    source_id = "claude_code_project"
    display_name = "Claude Code (project)"
    scope = "project"
    adapter = _mcp_adapter
    config_path_template = {
        "darwin": "{cwd}/.mcp.json",
        "linux": "{cwd}/.mcp.json",
        "windows": "{cwd}/.mcp.json",
    }


# --- Wave 1 new targets (S-309) ---


class _Windsurf(InjectionTarget):
    source_id = "windsurf"
    display_name = "Windsurf"
    scope = "global"
    adapter = _mcp_adapter
    config_path_template = {
        "darwin": "{home}/.codeium/windsurf/mcp_config.json",
        "linux": "{home}/.codeium/windsurf/mcp_config.json",
        "windows": "{home}/.codeium/windsurf/mcp_config.json",
    }


class _GeminiCLIGlobal(InjectionTarget):
    source_id = "gemini_cli_global"
    display_name = "Gemini CLI (global)"
    scope = "global"
    adapter = _mcp_adapter
    config_path_template = {
        "darwin": "{home}/.gemini/settings.json",
        "linux": "{home}/.gemini/settings.json",
        "windows": "{home}/.gemini/settings.json",
    }


class _GeminiCLIProject(InjectionTarget):
    source_id = "gemini_cli_project"
    display_name = "Gemini CLI (project)"
    scope = "project"
    adapter = _mcp_adapter
    config_path_template = {
        "darwin": "{cwd}/.gemini/settings.json",
        "linux": "{cwd}/.gemini/settings.json",
        "windows": "{cwd}/.gemini/settings.json",
    }


class _Cline(InjectionTarget):
    source_id = "cline"
    display_name = "Cline"
    scope = "global"
    adapter = _mcp_adapter
    config_path_template = {
        "darwin": (
            "{home}/Library/Application Support/Code/User/"
            "globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"
        ),
        "linux": (
            "{home}/.config/Code/User/"
            "globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"
        ),
        "windows": (
            "{home}/AppData/Roaming/Code/User/"
            "globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"
        ),
    }


# --- Wave 1 new targets (S-310: Microsoft servers shape) ---


class _VSCodeCopilotWorkspace(InjectionTarget):
    source_id = "vscode_copilot_workspace"
    display_name = "VS Code Copilot (workspace)"
    scope = "project"
    adapter = _ms_adapter
    config_path_template = {
        "darwin": "{cwd}/.vscode/mcp.json",
        "linux": "{cwd}/.vscode/mcp.json",
        "windows": "{cwd}/.vscode/mcp.json",
    }

    def make_ploston_entry(
        self,
        *,
        cp_url: str,
        expose: str | None = None,
        runner_name: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Microsoft shape requires "type": "stdio"."""
        entry = super().make_ploston_entry(
            cp_url=cp_url,
            expose=expose,
            runner_name=runner_name,
            tags=tags,
        )
        entry["type"] = "stdio"
        return entry


class _VSCodeCopilotUser(InjectionTarget):
    source_id = "vscode_copilot_user"
    display_name = "VS Code Copilot (user)"
    scope = "global"
    adapter = _ms_adapter
    config_path_template = {
        "darwin": "{home}/Library/Application Support/Code/User/mcp.json",
        "linux": "{home}/.config/Code/User/mcp.json",
        "windows": "{home}/AppData/Roaming/Code/User/mcp.json",
    }

    def make_ploston_entry(
        self,
        *,
        cp_url: str,
        expose: str | None = None,
        runner_name: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Microsoft shape requires "type": "stdio"."""
        entry = super().make_ploston_entry(
            cp_url=cp_url,
            expose=expose,
            runner_name=runner_name,
            tags=tags,
        )
        entry["type"] = "stdio"
        return entry


class _VisualStudioUser(InjectionTarget):
    source_id = "visual_studio_user"
    display_name = "Visual Studio 2022/2026 (user)"
    scope = "global"
    adapter = _ms_adapter
    # Windows only — darwin/linux entries deliberately absent.
    config_path_template = {
        "windows": "{home}/.mcp.json",
    }

    def make_ploston_entry(
        self,
        *,
        cp_url: str,
        expose: str | None = None,
        runner_name: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Microsoft shape requires "type": "stdio"."""
        entry = super().make_ploston_entry(
            cp_url=cp_url,
            expose=expose,
            runner_name=runner_name,
            tags=tags,
        )
        entry["type"] = "stdio"
        return entry


# ---------------------------------------------------------------------------
# TARGET_REGISTRY — the dispatch table
# ---------------------------------------------------------------------------


def _build_registry() -> dict[str, InjectionTarget]:
    """Build and return the target registry dict, keyed by source_id."""
    targets = [
        _ClaudeDesktop(),
        _CursorGlobal(),
        _CursorProject(),
        _ClaudeCodeGlobal(),
        _ClaudeCodeProject(),
        _Windsurf(),
        _GeminiCLIGlobal(),
        _GeminiCLIProject(),
        _Cline(),
        _VSCodeCopilotWorkspace(),
        _VSCodeCopilotUser(),
        _VisualStudioUser(),
    ]
    return {t.source_id: t for t in targets}


TARGET_REGISTRY: dict[str, InjectionTarget] = _build_registry()
