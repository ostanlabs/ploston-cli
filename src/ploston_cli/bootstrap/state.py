"""Bootstrap state management for idempotent operations.

This module provides state detection and management for the bootstrap
command, enabling idempotent behavior when running bootstrap multiple times.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..runner.daemon import is_running as runner_is_running
from ..runner.daemon import stop_daemon as stop_runner
from .compose import PLOSTON_DIR
from .stack import DEFAULT_NETWORK_NAME, STACK_CONFIG_FILE, StackManager, StackState

logger = logging.getLogger(__name__)


class BootstrapAction(Enum):
    """Actions available when bootstrap detects existing state."""

    FRESH_INSTALL = "fresh_install"  # No existing stack
    KEEP_RUNNING = "keep_running"  # Stack running, do nothing
    RESTART = "restart"  # Restart existing stack
    RECREATE = "recreate"  # Pull latest, regenerate, restart
    TEARDOWN = "teardown"  # Stop and remove stack


# Bootstrap-generated artifacts that should be cleaned before a fresh install.
# Each entry is (name, type) where type is "file" or "dir".
_GENERATED_ARTIFACTS: list[tuple[str, str]] = [
    ("docker-compose.yaml", "file"),
    ("ploston-config.yaml", "file"),
    (".env", "file"),
    (STACK_CONFIG_FILE, "file"),
    ("observability", "dir"),
    # Stale directories auto-created by Docker when bind-mount sources
    # didn't exist (old overlay had wrong relative paths).
    ("prometheus", "dir"),
    ("loki", "dir"),
    ("tempo", "dir"),
    ("otel", "dir"),
    ("grafana", "dir"),
    # Redis bind-mount data — must be wiped so the runner registry
    # (which stores token hashes) doesn't survive across bootstraps.
    ("data/redis", "dir"),
]


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
    # Stale artifacts present on disk or in Docker (name strings for display).
    stale_artifacts: list[str] = field(default_factory=list)

    @property
    def needs_cleanup(self) -> bool:
        """Whether any cleanup is needed before a fresh bootstrap.

        True if the stack is running OR any generated artifact exists
        (files, directories, Docker network).
        """
        return self.stack_running or bool(self.stale_artifacts)


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

        Scans for all bootstrap-generated artifacts (files, directories,
        Docker network) and populates ``stale_artifacts`` so that
        ``needs_cleanup`` reflects whether *anything* needs to be removed
        before a fresh install.

        Returns:
            BootstrapState with current installation status.
        """
        state = BootstrapState()

        # Check for existing files
        state.has_compose_file = (self.base_dir / "docker-compose.yaml").exists()
        state.has_config_file = (self.base_dir / "ploston-config.yaml").exists()
        state.has_env_file = (self.base_dir / ".env").exists()

        # Scan all generated artifacts (files + directories)
        artifacts: list[str] = []
        for name, kind in _GENERATED_ARTIFACTS:
            path = self.base_dir / name
            if kind == "file" and path.is_file():
                artifacts.append(name)
            elif kind == "dir" and path.is_dir():
                artifacts.append(f"{name}/")

        # Check for lingering Docker network
        if self._network_exists():
            artifacts.append(f"network:{DEFAULT_NETWORK_NAME}")

        state.stale_artifacts = artifacts

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
        elif state.stale_artifacts:
            state.suggested_action = BootstrapAction.TEARDOWN
        else:
            state.suggested_action = BootstrapAction.FRESH_INSTALL

        return state

    @staticmethod
    def _network_exists(network_name: str = DEFAULT_NETWORK_NAME) -> bool:
        """Check whether a Docker network exists.

        Best-effort — returns False on any error (Docker not installed, etc.).
        """
        try:
            result = subprocess.run(
                ["docker", "network", "inspect", network_name],
                capture_output=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_available_actions(self, state: BootstrapState) -> list[BootstrapAction]:
        """Get available actions based on current state.

        Args:
            state: Current bootstrap state.

        Returns:
            List of available actions.
        """
        # Nothing at all — pure fresh install.
        if not state.needs_cleanup:
            return [BootstrapAction.FRESH_INSTALL]

        actions = []
        if state.stack_running:
            actions.append(BootstrapAction.KEEP_RUNNING)
            actions.append(BootstrapAction.RESTART)
            actions.append(BootstrapAction.RECREATE)
        actions.append(BootstrapAction.TEARDOWN)

        return actions

    def execute_action(
        self,
        action: BootstrapAction,
        preserve_telemetry: bool = True,
        skip_pull: bool = False,
    ) -> tuple[bool, str]:
        """Execute a bootstrap action.

        Args:
            action: Action to execute.
            preserve_telemetry: If True (default), keep telemetry data
                (data/ploston) during teardown. If False, wipe it.
            skip_pull: If True, skip pulling images during RECREATE.
                Used when images are already built locally
                (e.g. --build-from-source).

        Returns:
            Tuple of (success, message).
        """
        if action == BootstrapAction.KEEP_RUNNING:
            return True, "Stack is running. Nothing to do."

        elif action == BootstrapAction.RESTART:
            return self.stack_manager.restart()

        elif action == BootstrapAction.RECREATE:
            if not skip_pull:
                # Pull latest images before restart
                success, msg = self.stack_manager.pull()
                if not success:
                    return False, f"Failed to pull images: {msg}"
            return self.stack_manager.restart()

        elif action == BootstrapAction.TEARDOWN:
            # Stop the runner daemon first — it connects to the CP stack
            # we're about to tear down, and its PID/log files live in the
            # directory we're about to clean.
            alive, pid = runner_is_running()
            if alive:
                logger.info("Stopping runner daemon (PID %s) before teardown", pid)
                stop_runner()

            success, msg = self.stack_manager.down(
                remove_volumes=not preserve_telemetry,
            )
            if not success:
                return False, msg
            self._cleanup_generated_files(preserve_telemetry=preserve_telemetry)
            return True, msg

        elif action == BootstrapAction.FRESH_INSTALL:
            return True, "Ready for fresh install"

        return False, f"Unknown action: {action}"

    @staticmethod
    def _force_remove_tree(path: Path) -> None:
        """Remove a directory tree, handling Docker-owned (root) files.

        Docker containers (e.g. Redis) create files owned by root inside
        bind-mounted host directories.  A plain ``shutil.rmtree`` fails with
        ``PermissionError`` on those files.  We fall back to
        ``docker run --rm -v …:/cleanup alpine rm -rf /cleanup`` which runs
        as root and can delete them, then retry the normal removal.
        """
        try:
            shutil.rmtree(path)
        except PermissionError:
            logger.debug("PermissionError removing %s — retrying via docker rm", path)
            try:
                subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "-v",
                        f"{path}:/cleanup",
                        "alpine",
                        "rm",
                        "-rf",
                        "/cleanup",
                    ],
                    capture_output=True,
                    timeout=30,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("docker rm fallback failed: %s", exc)
            # Final attempt — directory may now be empty or fully removed.
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)

    def _cleanup_generated_files(
        self,
        preserve_telemetry: bool = True,
    ) -> None:
        """Remove all bootstrap-generated files and directories.

        Uses the module-level ``_GENERATED_ARTIFACTS`` list so that detection
        and cleanup always agree on what counts as an artifact.
        Called during teardown so the next bootstrap starts from a clean slate.
        Preserves user state (runner logs, tokens, CA certs, data).

        Args:
            preserve_telemetry: If True (default), keep the ``data/ploston``
                directory containing the telemetry SQLite database.
                If False, wipe it along with other generated artifacts.
        """
        for name, kind in _GENERATED_ARTIFACTS:
            path = self.base_dir / name
            if kind == "file" and path.is_file():
                path.unlink()
                logger.debug("Removed %s", path)
            elif kind == "dir" and path.is_dir():
                self._force_remove_tree(path)
                logger.debug("Removed directory %s", path)

        # Conditionally wipe telemetry data (DEC-150).
        # data/ploston is NOT in _GENERATED_ARTIFACTS so it is preserved
        # by default — only wiped when the user explicitly opts out.
        if not preserve_telemetry:
            telemetry_dir = self.base_dir / "data" / "ploston"
            if telemetry_dir.is_dir():
                self._force_remove_tree(telemetry_dir)
                logger.debug("Removed telemetry data directory %s", telemetry_dir)

        # Conditionally wipe API-registered workflows.
        # data/workflows is NOT in _GENERATED_ARTIFACTS so it is preserved
        # by default — only wiped when the user explicitly opts out.
        if not preserve_telemetry:
            workflows_dir = self.base_dir / "data" / "workflows"
            if workflows_dir.is_dir():
                self._force_remove_tree(workflows_dir)
                logger.debug("Removed workflows data directory %s", workflows_dir)

    def cleanup(self, remove_data: bool = False) -> tuple[bool, str]:
        """Clean up bootstrap installation.

        Args:
            remove_data: Whether to remove data directories.

        Returns:
            Tuple of (success, message).
        """
        # Stop stack first
        self.stack_manager.down(remove_volumes=remove_data)

        # Remove all generated artifacts
        self._cleanup_generated_files()

        return True, "Bootstrap cleanup complete"
