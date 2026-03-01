"""Stack management for bootstrap command.

This module provides docker-compose stack lifecycle management
including start, stop, status, and logs.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# Default paths
PLOSTON_DIR = Path.home() / ".ploston"


class StackState(Enum):
    """State of the docker-compose stack."""

    NOT_FOUND = "not_found"  # No compose file
    STOPPED = "stopped"  # Compose file exists, services down
    PARTIAL = "partial"  # Some services running
    RUNNING = "running"  # All services running
    UNHEALTHY = "unhealthy"  # Running but not healthy


@dataclass
class StackStatus:
    """Status of the docker-compose stack."""

    state: StackState
    running_services: list[str] = field(default_factory=list)
    stopped_services: list[str] = field(default_factory=list)
    message: str = ""


class StackManager:
    """Manage docker-compose stack."""

    def __init__(self, compose_dir: Path | None = None):
        """Initialize stack manager.

        Args:
            compose_dir: Directory containing docker-compose.yaml.
                        Defaults to ~/.ploston/
        """
        self.compose_dir = compose_dir or PLOSTON_DIR
        self.compose_file = self.compose_dir / "docker-compose.yaml"

    def status(self) -> StackStatus:
        """Get current stack status.

        Returns:
            StackStatus with current state and service information.
        """
        if not self.compose_file.exists():
            return StackStatus(StackState.NOT_FOUND, message="No docker-compose.yaml found")

        try:
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(self.compose_file),
                    "ps",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                cwd=self.compose_dir,
            )

            if result.returncode != 0:
                return StackStatus(
                    StackState.STOPPED,
                    message=result.stderr.strip() or "Stack not running",
                )

            # Parse ps output - docker compose ps --format json returns one JSON per line
            output = result.stdout.strip()
            if not output:
                return StackStatus(StackState.STOPPED, message="No services found")

            services = []
            for line in output.splitlines():
                if line.strip():
                    try:
                        services.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

            if not services:
                return StackStatus(StackState.STOPPED, message="No services found")

            running = [
                s.get("Service", s.get("Name", "unknown"))
                for s in services
                if s.get("State") == "running"
            ]
            stopped = [
                s.get("Service", s.get("Name", "unknown"))
                for s in services
                if s.get("State") != "running"
            ]

            if len(running) == 0:
                state = StackState.STOPPED
            elif len(stopped) == 0:
                state = StackState.RUNNING
            else:
                state = StackState.PARTIAL

            return StackStatus(state, running, stopped)
        except FileNotFoundError:
            return StackStatus(
                StackState.NOT_FOUND,
                message="Docker not found. Is Docker installed?",
            )
        except Exception as e:
            return StackStatus(StackState.STOPPED, message=str(e))

    def up(self, pull: bool = True, detach: bool = True) -> tuple[bool, str]:
        """Start stack.

        Args:
            pull: Whether to pull images before starting.
            detach: Whether to run in detached mode.

        Returns:
            Tuple of (success, message).
        """
        if not self.compose_file.exists():
            return False, "No docker-compose.yaml found"

        try:
            # Pull images first if requested
            if pull:
                pull_result = subprocess.run(
                    ["docker", "compose", "-f", str(self.compose_file), "pull"],
                    cwd=self.compose_dir,
                    capture_output=True,
                    text=True,
                )
                if pull_result.returncode != 0:
                    return False, f"Failed to pull images: {pull_result.stderr}"

            # Start services
            args = ["docker", "compose", "-f", str(self.compose_file), "up"]
            if detach:
                args.append("-d")

            result = subprocess.run(
                args,
                cwd=self.compose_dir,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return False, f"Failed to start stack: {result.stderr}"

            return True, "Stack started successfully"
        except FileNotFoundError:
            return False, "Docker not found. Is Docker installed?"
        except Exception as e:
            return False, str(e)

    def down(self, remove_volumes: bool = False) -> tuple[bool, str]:
        """Stop stack.

        Args:
            remove_volumes: Whether to remove volumes.

        Returns:
            Tuple of (success, message).
        """
        if not self.compose_file.exists():
            return False, "No docker-compose.yaml found"

        try:
            args = ["docker", "compose", "-f", str(self.compose_file), "down"]
            if remove_volumes:
                args.append("-v")

            result = subprocess.run(
                args,
                cwd=self.compose_dir,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return False, f"Failed to stop stack: {result.stderr}"

            return True, "Stack stopped successfully"
        except FileNotFoundError:
            return False, "Docker not found. Is Docker installed?"
        except Exception as e:
            return False, str(e)

    def restart(self) -> tuple[bool, str]:
        """Restart stack.

        Returns:
            Tuple of (success, message).
        """
        success, msg = self.down()
        if not success:
            return False, f"Failed to stop: {msg}"

        return self.up(pull=False)

    def logs(
        self,
        service: str | None = None,
        follow: bool = False,
        tail: int | None = None,
    ) -> subprocess.Popen | None:
        """Show logs.

        Args:
            service: Specific service to show logs for.
            follow: Whether to follow log output.
            tail: Number of lines to show from end.

        Returns:
            Popen process if follow=True, None otherwise.
        """
        if not self.compose_file.exists():
            return None

        args = ["docker", "compose", "-f", str(self.compose_file), "logs"]
        if follow:
            args.append("-f")
        if tail:
            args.extend(["--tail", str(tail)])
        if service:
            args.append(service)

        if follow:
            # Return process for caller to manage
            return subprocess.Popen(args, cwd=self.compose_dir)
        else:
            subprocess.run(args, cwd=self.compose_dir)
            return None

    def pull(self) -> tuple[bool, str]:
        """Pull latest images.

        Returns:
            Tuple of (success, message).
        """
        if not self.compose_file.exists():
            return False, "No docker-compose.yaml found"

        try:
            result = subprocess.run(
                ["docker", "compose", "-f", str(self.compose_file), "pull"],
                cwd=self.compose_dir,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return False, f"Failed to pull images: {result.stderr}"

            return True, "Images pulled successfully"
        except FileNotFoundError:
            return False, "Docker not found. Is Docker installed?"
        except Exception as e:
            return False, str(e)
