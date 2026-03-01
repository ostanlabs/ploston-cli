"""Prerequisite detection for bootstrap command.

This module provides detection of Docker, Docker Compose, kubectl,
port availability, and image resolution.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
from dataclasses import dataclass


@dataclass
class DockerInfo:
    """Docker runtime detection result."""

    docker_available: bool
    docker_version: str | None = None
    compose_available: bool = False
    compose_version: str | None = None
    error: str | None = None


class DockerDetector:
    """Detect Docker Engine and Compose availability."""

    def detect(self) -> DockerInfo:
        """Check for Docker and Docker Compose."""
        # Check Docker
        docker_path = shutil.which("docker")
        if not docker_path:
            return DockerInfo(
                docker_available=False,
                error="Docker not found. Install Docker: https://docs.docker.com/get-docker/",
            )

        try:
            result = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return DockerInfo(
                    docker_available=False,
                    error=f"Docker not responding: {result.stderr.strip()}",
                )
            docker_version = result.stdout.strip()
        except subprocess.TimeoutExpired:
            return DockerInfo(
                docker_available=False,
                error="Docker not responding (timeout)",
            )

        # Check Docker Compose
        try:
            result = subprocess.run(
                ["docker", "compose", "version", "--short"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            compose_available = result.returncode == 0
            compose_version = result.stdout.strip() if compose_available else None
        except subprocess.TimeoutExpired:
            compose_available = False
            compose_version = None

        return DockerInfo(
            docker_available=True,
            docker_version=docker_version,
            compose_available=compose_available,
            compose_version=compose_version,
        )


@dataclass
class PortStatus:
    """Result of port availability check."""

    port: int
    available: bool
    service_name: str | None = None


class PortScanner:
    """Check port availability on localhost."""

    def check_ports(self, ports: dict[int, str]) -> list[PortStatus]:
        """Check if ports are available.

        Args:
            ports: dict of {port_number: service_name}

        Returns:
            List of PortStatus for each checked port.
        """
        results = []
        for port, service in ports.items():
            available = self._is_port_available(port)
            results.append(PortStatus(port, available, service))
        return results

    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available on localhost."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            return result != 0
        except Exception:
            return False

    def suggest_alternative(self, port: int) -> int:
        """Find next available port starting from given port."""
        candidate = port + 1
        while candidate < 65535:
            if self._is_port_available(candidate):
                return candidate
            candidate += 1
        raise RuntimeError("No available ports found")


@dataclass
class ImageResolution:
    """Result of image tag resolution."""

    image: str
    tag: str | None = None
    resolved_digest: str | None = None
    error: str | None = None


class ImageResolver:
    """Resolve Docker image tags."""

    def resolve(self, image: str, tag: str = "latest") -> ImageResolution:
        """Resolve an image tag to its digest.

        For now, just validate it can be pulled.

        Args:
            image: Docker image name (e.g., ghcr.io/ostanlabs/ploston)
            tag: Image tag (default: latest)

        Returns:
            ImageResolution with image info or error.
        """
        full_image = f"{image}:{tag}"
        try:
            # Try docker image inspect to check if locally available
            result = subprocess.run(
                ["docker", "image", "inspect", full_image],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Image is local, extract digest from inspection
                return ImageResolution(image, tag)

            # Not local, attempt pull to validate it exists
            # (will be done by ComposeGenerator, just check here)
            return ImageResolution(image, tag)
        except subprocess.TimeoutExpired:
            return ImageResolution(image, tag, error="Docker image inspect timed out")
        except Exception as e:
            return ImageResolution(image, tag, error=str(e))


@dataclass
class KubectlInfo:
    """kubectl and cluster detection result."""

    kubectl_available: bool
    kubectl_version: str | None = None
    cluster_reachable: bool = False
    cluster_info: str | None = None
    error: str | None = None


class KubectlDetector:
    """Detect kubectl and Kubernetes cluster availability."""

    def detect(self) -> KubectlInfo:
        """Check for kubectl and cluster connectivity."""
        kubectl_path = shutil.which("kubectl")
        if not kubectl_path:
            return KubectlInfo(
                kubectl_available=False,
                error="kubectl not found. Install kubectl: https://kubernetes.io/docs/tasks/tools/",
            )

        try:
            result = subprocess.run(
                ["kubectl", "version", "--client", "--short"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return KubectlInfo(
                    kubectl_available=False,
                    error=f"kubectl error: {result.stderr.strip()}",
                )
            kubectl_version = result.stdout.strip()
        except subprocess.TimeoutExpired:
            return KubectlInfo(
                kubectl_available=False,
                error="kubectl not responding (timeout)",
            )

        # Check cluster connectivity
        try:
            result = subprocess.run(
                ["kubectl", "cluster-info"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            cluster_reachable = result.returncode == 0
            cluster_info = result.stdout.strip() if cluster_reachable else result.stderr.strip()
        except subprocess.TimeoutExpired:
            cluster_reachable = False
            cluster_info = "Cluster check timed out"

        return KubectlInfo(
            kubectl_available=True,
            kubectl_version=kubectl_version,
            cluster_reachable=cluster_reachable,
            cluster_info=cluster_info,
        )
