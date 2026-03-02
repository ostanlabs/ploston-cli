"""Network conflict handling for bootstrap command."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from enum import Enum


class NetworkConflictAction(Enum):
    """User's choice for handling network conflict."""

    REMOVE = "remove"  # Remove existing network and retry
    USE = "use"  # Use existing network (mark as external)
    RENAME = "rename"  # Deploy to a different network name


@dataclass
class NetworkInfo:
    """Information about a Docker network."""

    name: str
    id: str
    driver: str
    scope: str
    containers: list[str] = field(default_factory=list)


@dataclass
class NetworkConflict:
    """Details about a network conflict."""

    network_name: str
    exists: bool = False
    network_info: NetworkInfo | None = None
    error_message: str = ""


class NetworkManager:
    """Manage Docker networks for bootstrap."""

    def __init__(self, network_name: str = "ploston-network"):
        self.network_name = network_name

    def check_network_exists(self) -> NetworkConflict:
        """Check if the network already exists and get its info.

        Returns:
            NetworkConflict with details about the existing network.
        """
        try:
            result = subprocess.run(
                ["docker", "network", "inspect", self.network_name],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                # Network doesn't exist
                return NetworkConflict(
                    network_name=self.network_name,
                    exists=False,
                )

            # Parse network info
            networks = json.loads(result.stdout)
            if not networks:
                return NetworkConflict(
                    network_name=self.network_name,
                    exists=False,
                )

            net = networks[0]
            containers = list(net.get("Containers", {}).values())
            container_names = [c.get("Name", "unknown") for c in containers]

            network_info = NetworkInfo(
                name=net.get("Name", self.network_name),
                id=net.get("Id", "")[:12],
                driver=net.get("Driver", "bridge"),
                scope=net.get("Scope", "local"),
                containers=container_names,
            )

            return NetworkConflict(
                network_name=self.network_name,
                exists=True,
                network_info=network_info,
            )

        except FileNotFoundError:
            return NetworkConflict(
                network_name=self.network_name,
                exists=False,
                error_message="Docker not found",
            )
        except json.JSONDecodeError:
            return NetworkConflict(
                network_name=self.network_name,
                exists=True,
                error_message="Could not parse network info",
            )
        except Exception as e:
            return NetworkConflict(
                network_name=self.network_name,
                exists=False,
                error_message=str(e),
            )

    def remove_network(self, force: bool = False) -> tuple[bool, str]:
        """Remove the network.

        Args:
            force: If True, disconnect containers first.

        Returns:
            Tuple of (success, message).
        """
        try:
            if force:
                # First disconnect all containers
                conflict = self.check_network_exists()
                if conflict.network_info and conflict.network_info.containers:
                    for container in conflict.network_info.containers:
                        subprocess.run(
                            [
                                "docker",
                                "network",
                                "disconnect",
                                "-f",
                                self.network_name,
                                container,
                            ],
                            capture_output=True,
                        )

            result = subprocess.run(
                ["docker", "network", "rm", self.network_name],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return False, f"Failed to remove network: {result.stderr.strip()}"

            return True, f"Network '{self.network_name}' removed"

        except Exception as e:
            return False, str(e)

    def get_services_on_network(self) -> list[str]:
        """Get list of container/service names on this network.

        Returns:
            List of container names.
        """
        conflict = self.check_network_exists()
        if conflict.network_info:
            return conflict.network_info.containers
        return []

    def suggest_alternative_name(self) -> str:
        """Suggest an alternative network name.

        Returns:
            Alternative network name that doesn't exist.
        """
        base_name = self.network_name.replace("-network", "")
        for i in range(2, 100):
            candidate = f"{base_name}-network-{i}"
            # Check if this network exists
            result = subprocess.run(
                ["docker", "network", "inspect", candidate],
                capture_output=True,
            )
            if result.returncode != 0:
                return candidate
        return f"{base_name}-network-new"

    def get_our_services(self) -> set[str]:
        """Get the set of service names that Ploston bootstrap creates.

        Returns:
            Set of container names that belong to Ploston.
        """
        return {"ploston-cp", "ploston-native-tools", "ploston-redis"}

    def check_service_conflicts(self) -> list[str]:
        """Check if any of our services are already running on the network.

        Returns:
            List of conflicting service names.
        """
        existing = set(self.get_services_on_network())
        our_services = self.get_our_services()
        return list(existing & our_services)
