"""Bootstrap state management for idempotent operations.

This module provides state detection and management for the bootstrap
command, enabling idempotent behavior when running bootstrap multiple times.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .compose import PLOSTON_DIR
from .stack import StackManager, StackState


class BootstrapAction(Enum):
    """Actions available when bootstrap detects existing state."""

    FRESH_INSTALL = "fresh_install"  # No existing stack
    KEEP_RUNNING = "keep_running"  # Stack running, do nothing
    RESTART = "restart"  # Restart existing stack
    RECREATE = "recreate"  # Pull latest, regenerate, restart
    TEARDOWN = "teardown"  # Stop and remove stack


@dataclass
class BootstrapState:
    """Current state of bootstrap installation."""

    has_compose_file: bool = False
    has_config_file: bool = False
    has_env_file: bool = False
    stack_running: bool = False
    stack_healthy: bool = False
    running_services: list[str] | None = None
    stopped_services: list[str] | None = None
    suggested_action: BootstrapAction = BootstrapAction.FRESH_INSTALL


class BootstrapStateManager:
    """Manage bootstrap state for idempotent operations."""

    def __init__(self, base_dir: Path | None = None):
        """Initialize state manager.

        Args:
            base_dir: Base directory for Ploston data (default: ~/.ploston)
        """
        self.base_dir = base_dir or PLOSTON_DIR
        self.stack_manager = StackManager(self.base_dir)

    def detect_state(self) -> BootstrapState:
        """Detect current bootstrap state.

        Returns:
            BootstrapState with current installation status.
        """
        state = BootstrapState()

        # Check for existing files
        state.has_compose_file = (self.base_dir / "docker-compose.yaml").exists()
        state.has_config_file = (self.base_dir / "ploston-config.yaml").exists()
        state.has_env_file = (self.base_dir / ".env").exists()

        # Check stack status
        stack_status = self.stack_manager.status()
        state.running_services = stack_status.running_services
        state.stopped_services = stack_status.stopped_services

        if stack_status.state == StackState.RUNNING:
            state.stack_running = True
            state.suggested_action = BootstrapAction.KEEP_RUNNING
        elif stack_status.state == StackState.PARTIAL:
            state.stack_running = True
            state.suggested_action = BootstrapAction.RESTART
        elif stack_status.state == StackState.STOPPED and state.has_compose_file:
            state.suggested_action = BootstrapAction.RESTART
        elif stack_status.state == StackState.NOT_FOUND:
            state.suggested_action = BootstrapAction.FRESH_INSTALL

        return state

    def get_available_actions(self, state: BootstrapState) -> list[BootstrapAction]:
        """Get available actions based on current state.

        Args:
            state: Current bootstrap state.

        Returns:
            List of available actions.
        """
        if not state.has_compose_file:
            return [BootstrapAction.FRESH_INSTALL]

        actions = []
        if state.stack_running:
            actions.append(BootstrapAction.KEEP_RUNNING)
            actions.append(BootstrapAction.RESTART)
            actions.append(BootstrapAction.RECREATE)
            actions.append(BootstrapAction.TEARDOWN)
        else:
            actions.append(BootstrapAction.RESTART)
            actions.append(BootstrapAction.RECREATE)
            actions.append(BootstrapAction.TEARDOWN)

        return actions

    def execute_action(self, action: BootstrapAction) -> tuple[bool, str]:
        """Execute a bootstrap action.

        Args:
            action: Action to execute.

        Returns:
            Tuple of (success, message).
        """
        if action == BootstrapAction.KEEP_RUNNING:
            return True, "Stack is running. Nothing to do."

        elif action == BootstrapAction.RESTART:
            return self.stack_manager.restart()

        elif action == BootstrapAction.RECREATE:
            # Pull latest images and restart
            success, msg = self.stack_manager.pull()
            if not success:
                return False, f"Failed to pull images: {msg}"
            return self.stack_manager.restart()

        elif action == BootstrapAction.TEARDOWN:
            return self.stack_manager.down()

        elif action == BootstrapAction.FRESH_INSTALL:
            return True, "Ready for fresh install"

        return False, f"Unknown action: {action}"

    def cleanup(self, remove_data: bool = False) -> tuple[bool, str]:
        """Clean up bootstrap installation.

        Args:
            remove_data: Whether to remove data directories.

        Returns:
            Tuple of (success, message).
        """
        # Stop stack first
        self.stack_manager.down(remove_volumes=remove_data)

        # Remove generated files
        files_to_remove = [
            self.base_dir / "docker-compose.yaml",
            self.base_dir / "ploston-config.yaml",
            self.base_dir / ".env",
        ]

        for f in files_to_remove:
            if f.exists():
                f.unlink()

        return True, "Bootstrap cleanup complete"
