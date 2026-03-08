"""Init import integration for bootstrap command.

This module provides integration between bootstrap and the init --import
flow, enabling auto-detection of Claude/Cursor configs and seamless
handoff to the import process.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field

from ..init.detector import ConfigDetector, DetectedConfig, ServerInfo, merge_configs
from ..init.env_manager import load_env_file
from ..init.injector import default_runner_name

logger = logging.getLogger(__name__)


@dataclass
class AutoChainResult:
    """Result of auto-chain detection."""

    configs_found: bool = False
    claude_config: DetectedConfig | None = None
    cursor_config: DetectedConfig | None = None
    total_servers: int = 0
    server_names: list[str] | None = None
    # Merged servers dict for direct use by bootstrap (avoids re-detection)
    servers: dict[str, ServerInfo] = field(default_factory=dict)
    # All detected configs (for injection step)
    detected_configs: list[DetectedConfig] = field(default_factory=list)


class AutoChainDetector:
    """Detect Claude/Cursor configs for auto-chaining to init --import."""

    def __init__(self):
        """Initialize detector."""
        self.config_detector = ConfigDetector()

    def detect(self) -> AutoChainResult:
        """Detect existing MCP configurations.

        Returns:
            AutoChainResult with detection status.
        """
        configs = self.config_detector.detect_all()

        claude_config = None
        cursor_config = None
        found_configs = []

        for config in configs:
            if config.source == "claude_desktop":
                claude_config = config
            elif config.source == "cursor":
                cursor_config = config
            if config.found:
                found_configs.append(config)

        # Merge and count servers
        merged = merge_configs(configs)
        server_names = list(merged.keys())

        return AutoChainResult(
            configs_found=len(merged) > 0,
            claude_config=claude_config,
            cursor_config=cursor_config,
            total_servers=len(merged),
            server_names=server_names,
            servers=merged,
            detected_configs=found_configs,
        )


class ImportHandoff:
    """Handle handoff to init --import flow."""

    def __init__(self, cp_url: str = "http://localhost:8022"):
        """Initialize handoff.

        Args:
            cp_url: URL of the Control Plane.
        """
        self.cp_url = cp_url

    def run_import(
        self,
        source: str | None = None,
        dry_run: bool = False,
        interactive: bool = True,
        inject: bool = False,
    ) -> tuple[bool, str]:
        """Run the init --import command.

        Args:
            source: Specific source to import from (claude_desktop, cursor, or path).
            dry_run: If True, only show what would be imported.
            interactive: If True, prompt for confirmation.
            inject: If True, inject Ploston into source config files.

        Returns:
            Tuple of (success, message).
        """
        # Build command
        cmd = ["ploston", "init", "--import", "--cp-url", self.cp_url]

        if source:
            cmd.extend(["--source", source])

        if dry_run:
            cmd.append("--dry-run")

        if not interactive:
            cmd.append("--non-interactive")

        if inject:
            cmd.append("--inject")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, result.stderr or "Import failed"
        except FileNotFoundError:
            return False, "ploston CLI not found"
        except Exception as e:
            return False, str(e)


class RunnerAutoStart:
    """Handle automatic runner start after import."""

    def __init__(self, cp_url: str = "http://localhost:8022"):
        """Initialize runner auto-start.

        Args:
            cp_url: HTTP URL of the Control Plane (e.g. http://localhost:8022).
        """
        self.cp_url = cp_url

    def _get_ws_url(self) -> str:
        """Convert HTTP CP URL to WebSocket runner endpoint.

        Returns:
            WebSocket URL for runner connection (e.g. ws://localhost:8022/api/v1/runner/ws).
        """
        return f"{self.cp_url.replace('http', 'ws')}/api/v1/runner/ws"

    def _get_runner_token(self) -> str | None:
        """Read runner token from ~/.ploston/.env.

        The token is written there by `ploston init --import`.

        Returns:
            Token string, or None if not found.
        """
        env_vars = load_env_file()
        return env_vars.get("PLOSTON_RUNNER_TOKEN")

    def _get_runner_name(self) -> str:
        """Get runner name (sanitised hostname).

        Returns:
            Runner name string.
        """
        return default_runner_name()

    def start_runner(self, daemon: bool = True) -> tuple[bool, str]:
        """Start the local runner.

        Reads the runner token from ~/.ploston/.env (written by init --import)
        and uses the machine hostname as the runner name.

        Args:
            daemon: If True, start as background daemon.

        Returns:
            Tuple of (success, message).
        """
        token = self._get_runner_token()
        if not token:
            return False, "Runner token not found in ~/.ploston/.env (was init --import run?)"

        name = self._get_runner_name()
        ws_url = self._get_ws_url()

        cmd = ["ploston", "runner", "start", "--cp", ws_url, "--token", token, "--name", name]

        if daemon:
            cmd.append("--daemon")

        logger.debug("Starting runner: %s", " ".join(cmd[:6] + ["***", "--name", name]))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                return True, "Runner started successfully"
            else:
                # The daemon writes errors to stdout (via print()), not stderr.
                error = result.stderr.strip() or result.stdout.strip() or "Failed to start runner"
                return False, error
        except FileNotFoundError:
            return False, "ploston CLI not found"
        except Exception as e:
            return False, str(e)

    def check_runner_status(self) -> tuple[bool, str]:
        """Check if runner is already running.

        Returns:
            Tuple of (running, message).
        """
        cmd = ["ploston", "runner", "status"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, "Runner not running"
        except FileNotFoundError:
            return False, "ploston CLI not found"
        except Exception as e:
            return False, str(e)
