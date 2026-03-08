"""Stack management for bootstrap command.

This module provides docker-compose stack lifecycle management
including start, stop, status, and logs.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import bootstrap_log as blog

logger = logging.getLogger(__name__)

# Default paths
PLOSTON_DIR = Path.home() / ".ploston"
DEFAULT_NETWORK_NAME = "ploston-network"
STACK_CONFIG_FILE = ".stack-config"

# Docker Compose V2 progress prefixes that are not errors
_COMPOSE_PROGRESS_PREFIXES = (
    " Network ",
    " Volume ",
    " Container ",
)


def _extract_docker_error(stderr: str) -> str:
    """Extract actual error lines from Docker Compose V2 stderr.

    Docker Compose V2 writes all progress output (Creating, Starting, etc.)
    to stderr.  This function filters out progress lines and returns only
    the lines that indicate an actual error.

    Args:
        stderr: Raw stderr from docker compose.

    Returns:
        Filtered error message, or the full stderr if no error lines found.
    """
    lines = stderr.splitlines()
    error_lines = [
        line
        for line in lines
        if line.strip()
        and not any(
            line.strip().startswith(prefix.strip()) for prefix in _COMPOSE_PROGRESS_PREFIXES
        )
    ]
    if error_lines:
        return "\n".join(line.strip() for line in error_lines)
    # No recognizable error lines — return the last few non-empty lines as context
    non_empty = [line.strip() for line in lines if line.strip()]
    return "\n".join(non_empty[-5:]) if non_empty else stderr


def save_stack_config(
    compose_files: list[Path],
    base_dir: Path | None = None,
) -> Path:
    """Persist the list of compose files used to deploy the stack.

    Writes one absolute path per line to ``{base_dir}/.stack-config``.
    This file is the single source of truth for which compose files
    the current stack was deployed with.

    Args:
        compose_files: Ordered list of compose file paths.
        base_dir: Base directory (default ``~/.ploston``).

    Returns:
        Path to the written ``.stack-config`` file.
    """
    base = base_dir or PLOSTON_DIR
    config_path = base / STACK_CONFIG_FILE
    config_path.write_text("\n".join(str(f.resolve()) for f in compose_files) + "\n")
    logger.debug("Saved stack config: %s", config_path)
    return config_path


def load_stack_config(base_dir: Path | None = None) -> list[Path] | None:
    """Load the compose file list from ``.stack-config``.

    Args:
        base_dir: Base directory (default ``~/.ploston``).

    Returns:
        Ordered list of compose file paths, or ``None`` if the
        config file does not exist.
    """
    base = base_dir or PLOSTON_DIR
    config_path = base / STACK_CONFIG_FILE
    if not config_path.is_file():
        return None
    lines = config_path.read_text().strip().splitlines()
    paths = [Path(line.strip()) for line in lines if line.strip()]
    if not paths:
        return None
    logger.debug("Loaded stack config: %s", paths)
    return paths


class StackState(Enum):
    """State of the docker-compose stack."""

    NOT_FOUND = "not_found"  # No compose file
    STOPPED = "stopped"  # Compose file exists, services down
    PARTIAL = "partial"  # Some services running
    RUNNING = "running"  # All services running
    UNHEALTHY = "unhealthy"  # Running but not healthy


@dataclass
class ServiceInfo:
    """Detailed info for a single docker-compose service."""

    name: str
    state: str  # "running", "exited", …
    health: str  # "healthy", "unhealthy", "starting", "" (no healthcheck)
    ports: list[str] = field(default_factory=list)  # e.g. ["8022", "3000"]
    status: str = ""  # human-readable, e.g. "Up 11 minutes (healthy)"


@dataclass
class StackStatus:
    """Status of the docker-compose stack."""

    state: StackState
    running_services: list[str] = field(default_factory=list)
    stopped_services: list[str] = field(default_factory=list)
    service_details: list[ServiceInfo] = field(default_factory=list)
    message: str = ""


class StackManager:
    """Manage docker-compose stack."""

    def __init__(
        self,
        compose_dir: Path | None = None,
        compose_files: list[Path] | None = None,
    ):
        """Initialize stack manager.

        Args:
            compose_dir: Directory containing docker-compose.yaml.
                        Defaults to ~/.ploston/
            compose_files: Optional list of compose files to use.
                          If not provided, reads from ``.stack-config``
                          (the single source of truth written at deploy time).
                          Falls back to ``[compose_dir/docker-compose.yaml]``
                          if ``.stack-config`` does not exist.
                          When multiple files are provided, they are layered
                          using docker compose -f file1 -f file2.
        """
        self.compose_dir = compose_dir or PLOSTON_DIR
        if compose_files:
            self._compose_files = compose_files
        else:
            persisted = load_stack_config(self.compose_dir)
            if persisted:
                self._compose_files = persisted
            else:
                self._compose_files = [self.compose_dir / "docker-compose.yaml"]

    @property
    def compose_file(self) -> Path:
        """Primary compose file (first in the list).

        Returns:
            Path to the primary docker-compose.yaml file.
        """
        return self._compose_files[0]

    @property
    def compose_files(self) -> list[Path]:
        """All compose files in layering order.

        Returns:
            List of compose file paths.
        """
        return list(self._compose_files)

    def _compose_args(self) -> list[str]:
        """Build the docker compose -f arguments.

        Returns:
            List of command-line arguments for docker compose.
        """
        args: list[str] = ["docker", "compose"]
        for f in self._compose_files:
            args.extend(["-f", str(f)])
        return args

    def status(self) -> StackStatus:
        """Get current stack status.

        Returns:
            StackStatus with current state and service information.
        """
        if not self.compose_file.exists():
            return StackStatus(StackState.NOT_FOUND, message="No docker-compose.yaml found")

        try:
            result = subprocess.run(
                self._compose_args() + ["ps", "--format", "json"],
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

            running: list[str] = []
            stopped: list[str] = []
            details: list[ServiceInfo] = []

            for s in services:
                svc_name = s.get("Service", s.get("Name", "unknown"))
                svc_state = s.get("State", "")
                if svc_state == "running":
                    running.append(svc_name)
                else:
                    stopped.append(svc_name)

                # Extract published host ports from Publishers list
                host_ports: list[str] = []
                for pub in s.get("Publishers", []):
                    port = pub.get("PublishedPort", 0)
                    if port and pub.get("URL") not in ("::", ""):
                        host_ports.append(str(port))
                    elif port and pub.get("URL") == "":
                        # No explicit host binding but port is mapped
                        host_ports.append(str(port))

                # Deduplicate (IPv4 + IPv6 produce two entries per port)
                seen: set[str] = set()
                unique_ports: list[str] = []
                for p in host_ports:
                    if p not in seen and p != "0":
                        seen.add(p)
                        unique_ports.append(p)

                details.append(
                    ServiceInfo(
                        name=svc_name,
                        state=svc_state,
                        health=s.get("Health", ""),
                        ports=unique_ports,
                        status=s.get("Status", ""),
                    )
                )

            if len(running) == 0:
                state = StackState.STOPPED
            elif len(stopped) == 0:
                state = StackState.RUNNING
            else:
                state = StackState.PARTIAL

            return StackStatus(state, running, stopped, details)
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
            blog.step("StackManager.up — pre-deploy state")
            blog.info("pull", str(pull))
            blog.info("detach", str(detach))
            blog.info("compose_dir", str(self.compose_dir))
            blog.info("compose_files", str([str(f) for f in self._compose_files]))

            # Log compose file contents so we can see exactly what is being deployed
            for cf in self._compose_files:
                blog.log_file_contents(cf)

            # Snapshot Docker state before we touch anything
            blog.log_docker_state("pre-deploy docker state")

            # Clean up any stale network references before starting.
            blog.step("StackManager.up — network cleanup")
            self._cleanup_network()

            # Snapshot after cleanup
            blog.log_docker_state("post-cleanup docker state")

            # Pull images first if requested
            if pull:
                blog.step("StackManager.up — pull images")
                pull_args = self._compose_args() + ["pull"]
                pull_result = blog.log_subprocess(
                    pull_args,
                    cwd=self.compose_dir,
                    label="docker compose pull",
                )
                if pull_result.returncode != 0:
                    return False, f"Failed to pull images: {pull_result.stderr}"

            # Start services
            blog.step("StackManager.up — compose up")
            args = self._compose_args() + ["up"]
            if not pull:
                # When using pre-built local images (e.g. --build-from-source),
                # pass --no-build to prevent Docker Compose V2 from attempting
                # to build services that have no build context, which causes a
                # "No services to build" warning and non-zero exit code.
                args.append("--no-build")
            if detach:
                args.append("-d")

            result = blog.log_subprocess(
                args,
                cwd=self.compose_dir,
                label="docker compose up",
            )

            # Snapshot Docker state after compose up (regardless of success)
            blog.log_docker_state("post-up docker state")

            if result.returncode != 0:
                # Docker Compose V2 writes all progress to stderr.  Extract
                # only the actual error lines so the user sees what went wrong
                # instead of a wall of "Container X Creating" messages.
                error_detail = _extract_docker_error(result.stderr)
                blog.detail(f"EXTRACTED ERROR: {error_detail}")
                return False, f"Failed to start stack: {error_detail}"

            return True, "Stack started successfully"
        except FileNotFoundError:
            return False, "Docker not found. Is Docker installed?"
        except Exception as e:
            blog.detail(f"EXCEPTION in up(): {e}")
            return False, str(e)

    def down(self, remove_volumes: bool = False) -> tuple[bool, str]:
        """Stop stack and clean up the Docker network.

        Args:
            remove_volumes: Whether to remove volumes.

        Returns:
            Tuple of (success, message).
        """
        if not self.compose_file.exists():
            # No compose file — nothing to `docker compose down`, but the
            # network may still be lingering from a previous run.  Clean it
            # up so the next bootstrap starts from a clean slate.
            self._cleanup_network()
            return True, "No docker-compose.yaml found; network cleaned up"

        try:
            args = self._compose_args() + ["down", "--remove-orphans"]
            if remove_volumes:
                args.append("-v")

            blog.step("StackManager.down")
            blog.info("compose_files", str([str(f) for f in self._compose_files]))
            result = blog.log_subprocess(
                args,
                cwd=self.compose_dir,
                label="docker compose down",
            )

            if result.returncode != 0:
                return False, f"Failed to stop stack: {result.stderr}"

            # Clean up the Docker network to avoid stale references on next bootstrap.
            # docker compose down removes containers but may leave the network behind
            # if other containers or stale references are attached to it.
            self._cleanup_network()

            return True, "Stack stopped successfully"
        except FileNotFoundError:
            return False, "Docker not found. Is Docker installed?"
        except Exception as e:
            return False, str(e)

    def _cleanup_network(self) -> None:
        """Remove the ploston network if it still exists after compose down.

        Tries to read the network name from the compose file's network config.
        Falls back to DEFAULT_NETWORK_NAME when the compose file is missing or
        unparseable.  Force-disconnects any lingering containers before removal.
        Failures are silently ignored since this is best-effort cleanup.
        """
        import yaml

        network_name = None
        try:
            content = self.compose_file.read_text()
            compose_data = yaml.safe_load(content)
            networks = compose_data.get("networks", {})
            default_net = networks.get("default", {})
            network_name = default_net.get("name")
        except Exception:
            pass

        if not network_name:
            network_name = DEFAULT_NETWORK_NAME

        blog.info("cleanup_network", network_name)

        # Force-disconnect any containers still attached to the network.
        try:
            inspect = blog.log_subprocess(
                [
                    "docker",
                    "network",
                    "inspect",
                    network_name,
                    "--format",
                    "{{range .Containers}}{{.Name}} {{end}}",
                ],
                label=f"network inspect {network_name}",
            )
            if inspect.returncode == 0 and inspect.stdout.strip():
                for container in inspect.stdout.strip().split():
                    blog.log_subprocess(
                        ["docker", "network", "disconnect", "-f", network_name, container],
                        label=f"network disconnect {container}",
                    )
        except Exception:
            pass

        # Best-effort removal — ignore errors (network may already be gone)
        blog.log_subprocess(
            ["docker", "network", "rm", network_name],
            label=f"network rm {network_name}",
        )

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

        args = self._compose_args() + ["logs"]
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
                self._compose_args() + ["pull"],
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
