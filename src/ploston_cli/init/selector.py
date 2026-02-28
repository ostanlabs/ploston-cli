"""Server Selector - Interactive server selection for import flow.

This module provides an interactive UI for selecting which MCP servers
to import from detected configurations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import questionary
from questionary import Choice

from .detector import ServerInfo

if TYPE_CHECKING:
    from ploston_core.config.secrets import SecretDetector


class ServerSelector:
    """Interactive server selection for import flow.

    Uses questionary for checkbox-based selection with keyboard navigation.
    """

    def __init__(self, secret_detector: "SecretDetector | None" = None):
        """Initialize selector.

        Args:
            secret_detector: Optional SecretDetector for env var checking
        """
        self.secret_detector = secret_detector

    def prompt_selection(self, server_infos: list[ServerInfo]) -> list[str]:
        """Show interactive checkbox selection.

        Args:
            server_infos: List of ServerInfo objects to display

        Returns:
            List of selected server names

        Raises:
            KeyboardInterrupt: If user cancels (Ctrl+C)
        """
        if not server_infos:
            return []

        choices = []
        for info in server_infos:
            # Pre-select if all env vars are available (or no env vars needed)
            all_env_ok = info.all_env_vars_set

            # Build display title
            title = self._format_server_choice(info)
            choices.append(
                Choice(
                    title=title,
                    value=info.name,
                    checked=all_env_ok,
                )
            )

        selected = questionary.checkbox(
            "Select servers to import (↑↓ navigate, Space toggle, Enter confirm):",
            choices=choices,
        ).ask()

        if selected is None:
            # User cancelled (Ctrl+C)
            raise KeyboardInterrupt("Import cancelled by user")

        return selected

    def select_all(self, server_infos: list[ServerInfo]) -> list[str]:
        """Non-interactive mode: select all servers.

        Args:
            server_infos: List of ServerInfo objects

        Returns:
            List of all server names
        """
        return [info.name for info in server_infos]

    def _format_server_choice(self, info: ServerInfo) -> str:
        """Format a server for display in the selection UI.

        Args:
            info: ServerInfo to format

        Returns:
            Formatted string for display
        """
        # Server name and command
        name_part = f"{info.name:<20s}"
        cmd_part = info.display_command

        # Environment variable status
        env_status = self._format_env_status(info)

        # Combine into multi-line display
        if env_status:
            return f"{name_part} {cmd_part}\n{'':>22s}{env_status}"
        return f"{name_part} {cmd_part}"

    def _format_env_status(self, info: ServerInfo) -> str:
        """Format environment variable status for display.

        Args:
            info: ServerInfo to check

        Returns:
            Status string like "✓ GITHUB_TOKEN (set)" or "⚠ API_KEY (not set)"
        """
        if not info.env_vars_required:
            return ""

        parts = []
        for var in info.env_vars_required:
            is_set = info.env_vars_available.get(var, False)
            if is_set:
                parts.append(f"✓ {var}")
            else:
                parts.append(f"⚠ {var} (not set)")

        return " | ".join(parts)


def display_import_summary(
    selected_names: list[str],
    runner_name: str = "local",
) -> None:
    """Display a summary of the import selection.

    Args:
        selected_names: List of selected server names
        runner_name: Name of the runner that will execute the servers
    """
    count = len(selected_names)
    if count == 0:
        print("No servers selected.")
    elif count == 1:
        print(f"1 server selected → will run via local runner '{runner_name}'")
    else:
        print(f"{count} servers selected → will run via local runner '{runner_name}'")
