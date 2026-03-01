"""Init import integration for bootstrap command.

This module provides integration between bootstrap and the init --import
flow, enabling auto-detection of Claude/Cursor configs and seamless
handoff to the import process.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from ..init.detector import ConfigDetector, DetectedConfig, merge_configs


@dataclass
class AutoChainResult:
    """Result of auto-chain detection."""

    configs_found: bool = False
    claude_config: DetectedConfig | None = None
    cursor_config: DetectedConfig | None = None
    total_servers: int = 0
    server_names: list[str] | None = None


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

        for config in configs:
            if config.source == "claude_desktop":
                claude_config = config
            elif config.source == "cursor":
                cursor_config = config

        # Merge and count servers
        merged = merge_configs(configs)
        server_names = list(merged.keys())

        return AutoChainResult(
            configs_found=len(merged) > 0,
            claude_config=claude_config,
            cursor_config=cursor_config,
            total_servers=len(merged),
            server_names=server_names,
        )


class ImportHandoff:
    """Handle handoff to init --import flow."""

    def __init__(self, cp_url: str = "http://localhost:8082"):
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
    ) -> tuple[bool, str]:
        """Run the init --import command.

        Args:
            source: Specific source to import from (claude_desktop, cursor, or path).
            dry_run: If True, only show what would be imported.
            interactive: If True, prompt for confirmation.

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
            cmd.append("--yes")

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

    def __init__(self, cp_url: str = "http://localhost:8082"):
        """Initialize runner auto-start.

        Args:
            cp_url: URL of the Control Plane.
        """
        self.cp_url = cp_url

    def start_runner(self, daemon: bool = True) -> tuple[bool, str]:
        """Start the local runner.

        Args:
            daemon: If True, start as background daemon.

        Returns:
            Tuple of (success, message).
        """
        cmd = ["ploston", "runner", "start", "--cp-url", self.cp_url]

        if daemon:
            cmd.append("--daemon")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                return True, "Runner started successfully"
            else:
                return False, result.stderr or "Failed to start runner"
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
