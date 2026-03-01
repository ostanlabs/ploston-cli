"""Kubernetes manifest generation for bootstrap command.

This module generates Kubernetes manifests for deploying
the Ploston Control Plane stack to a K8s cluster.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Default paths
PLOSTON_DIR = Path.home() / ".ploston"
K8S_DIR = PLOSTON_DIR / "k8s"

# Default registry and images
DEFAULT_REGISTRY = "ghcr.io/ostanlabs"
DEFAULT_PLOSTON_IMAGE = "ploston-dev"
DEFAULT_NATIVE_TOOLS_IMAGE = "native-tools-dev"


@dataclass
class K8sConfig:
    """Configuration for K8s deployment."""

    namespace: str = "ploston"
    tag: str = "latest"
    port: int = 8082
    redis_port: int = 6379
    registry: str = DEFAULT_REGISTRY
    ploston_image: str = DEFAULT_PLOSTON_IMAGE
    native_tools_image: str = DEFAULT_NATIVE_TOOLS_IMAGE
    output_dir: Path | None = None


class K8sManifestGenerator:
    """Generate Kubernetes manifests."""

    def generate(self, config: K8sConfig) -> Path:
        """Generate K8s manifests in ~/.ploston/k8s/

        Args:
            config: Configuration for K8s deployment.

        Returns:
            Path to the generated manifests directory.
        """
        output_dir = config.output_dir or K8S_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        # Generate namespace manifest
        self._write_manifest(
            output_dir / "namespace.yaml",
            self._build_namespace(config),
        )

        # Generate service manifests
        self._write_manifest(
            output_dir / "redis.yaml",
            self._build_redis(config),
        )
        self._write_manifest(
            output_dir / "native-tools.yaml",
            self._build_native_tools(config),
        )
        self._write_manifest(
            output_dir / "ploston.yaml",
            self._build_ploston(config),
        )

        return output_dir

    def _write_manifest(self, path: Path, manifests: list[dict[str, Any]]) -> None:
        """Write manifests to file (multi-document YAML)."""
        with open(path, "w") as f:
            yaml.dump_all(manifests, f, default_flow_style=False, sort_keys=False)

    def _build_namespace(self, config: K8sConfig) -> list[dict[str, Any]]:
        """Build namespace manifest."""
        return [
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": config.namespace},
            }
        ]

    def _build_redis(self, config: K8sConfig) -> list[dict[str, Any]]:
        """Build Redis deployment and service."""
        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "redis", "namespace": config.namespace},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": "redis"}},
                "template": {
                    "metadata": {"labels": {"app": "redis"}},
                    "spec": {
                        "containers": [
                            {
                                "name": "redis",
                                "image": "redis:7-alpine",
                                "ports": [{"containerPort": 6379}],
                                "command": ["redis-server", "--appendonly", "yes"],
                                "volumeMounts": [{"name": "data", "mountPath": "/data"}],
                                "readinessProbe": {
                                    "exec": {"command": ["redis-cli", "ping"]},
                                    "initialDelaySeconds": 5,
                                    "periodSeconds": 5,
                                },
                            }
                        ],
                        "volumes": [{"name": "data", "emptyDir": {}}],
                    },
                },
            },
        }

        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "redis", "namespace": config.namespace},
            "spec": {
                "selector": {"app": "redis"},
                "ports": [{"port": 6379, "targetPort": 6379}],
            },
        }

        return [deployment, service]

    def _build_native_tools(self, config: K8sConfig) -> list[dict[str, Any]]:
        """Build native-tools deployment and service."""
        image = f"{config.registry}/{config.native_tools_image}:{config.tag}"

        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "native-tools", "namespace": config.namespace},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": "native-tools"}},
                "template": {
                    "metadata": {"labels": {"app": "native-tools"}},
                    "spec": {
                        "containers": [
                            {
                                "name": "native-tools",
                                "image": image,
                                "ports": [{"containerPort": 8081}],
                                "env": [
                                    {"name": "NATIVE_TOOLS_HOST", "value": "0.0.0.0"},
                                    {"name": "NATIVE_TOOLS_PORT", "value": "8081"},
                                    {"name": "REDIS_URL", "value": "redis://redis:6379/0"},
                                ],
                                "readinessProbe": {
                                    "httpGet": {"path": "/health", "port": 8081},
                                    "initialDelaySeconds": 10,
                                    "periodSeconds": 10,
                                },
                            }
                        ],
                    },
                },
            },
        }

        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "native-tools", "namespace": config.namespace},
            "spec": {
                "selector": {"app": "native-tools"},
                "ports": [{"port": 8081, "targetPort": 8081}],
            },
        }

        return [deployment, service]

    def _build_ploston(self, config: K8sConfig) -> list[dict[str, Any]]:
        """Build Ploston CP deployment and service."""
        image = f"{config.registry}/{config.ploston_image}:{config.tag}"

        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "ploston", "namespace": config.namespace},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": "ploston"}},
                "template": {
                    "metadata": {"labels": {"app": "ploston"}},
                    "spec": {
                        "containers": [
                            {
                                "name": "ploston",
                                "image": image,
                                "ports": [{"containerPort": 8082}],
                                "env": [
                                    {"name": "PLOSTON_HOST", "value": "0.0.0.0"},
                                    {"name": "PLOSTON_PORT", "value": "8082"},
                                    {"name": "REDIS_URL", "value": "redis://redis:6379/0"},
                                    {
                                        "name": "NATIVE_TOOLS_URL",
                                        "value": "http://native-tools:8081",
                                    },
                                ],
                                "readinessProbe": {
                                    "httpGet": {"path": "/health", "port": 8082},
                                    "initialDelaySeconds": 15,
                                    "periodSeconds": 10,
                                },
                            }
                        ],
                    },
                },
            },
        }

        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "ploston", "namespace": config.namespace},
            "spec": {
                "selector": {"app": "ploston"},
                "ports": [{"port": config.port, "targetPort": 8082}],
            },
        }

        return [deployment, service]


class KubectlDeployer:
    """Deploy manifests using kubectl."""

    def __init__(self, kubeconfig: str | None = None):
        """Initialize deployer.

        Args:
            kubeconfig: Path to kubeconfig file.
        """
        self.kubeconfig = kubeconfig

    def _kubectl_cmd(self) -> list[str]:
        """Build base kubectl command."""
        cmd = ["kubectl"]
        if self.kubeconfig:
            cmd.extend(["--kubeconfig", self.kubeconfig])
        return cmd

    def apply(self, manifest_dir: Path) -> tuple[bool, str]:
        """Apply all manifests in directory.

        Args:
            manifest_dir: Directory containing YAML manifests.

        Returns:
            Tuple of (success, message).
        """
        try:
            # Apply all YAML files in order
            for yaml_file in sorted(manifest_dir.glob("*.yaml")):
                result = subprocess.run(
                    self._kubectl_cmd() + ["apply", "-f", str(yaml_file)],
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    return False, f"Failed to apply {yaml_file.name}: {result.stderr}"

            return True, "Manifests applied successfully"
        except FileNotFoundError:
            return False, "kubectl not found. Is kubectl installed?"
        except Exception as e:
            return False, str(e)

    def delete_namespace(self, namespace: str) -> tuple[bool, str]:
        """Delete a namespace.

        Args:
            namespace: Namespace to delete.

        Returns:
            Tuple of (success, message).
        """
        try:
            result = subprocess.run(
                self._kubectl_cmd() + ["delete", "namespace", namespace],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return False, f"Failed to delete namespace: {result.stderr}"
            return True, f"Namespace '{namespace}' deleted"
        except FileNotFoundError:
            return False, "kubectl not found"
        except Exception as e:
            return False, str(e)

    def port_forward(
        self,
        namespace: str,
        service: str,
        local_port: int,
        remote_port: int,
    ) -> subprocess.Popen | None:
        """Start port forwarding.

        Args:
            namespace: K8s namespace.
            service: Service name.
            local_port: Local port to forward to.
            remote_port: Remote port on the service.

        Returns:
            Popen process for the port-forward, or None on error.
        """
        try:
            return subprocess.Popen(
                self._kubectl_cmd()
                + [
                    "-n",
                    namespace,
                    "port-forward",
                    f"svc/{service}",
                    f"{local_port}:{remote_port}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return None


class K8sHealthCheck:
    """Check health of K8s deployment."""

    def __init__(self, kubeconfig: str | None = None):
        """Initialize health checker.

        Args:
            kubeconfig: Path to kubeconfig file.
        """
        self.kubeconfig = kubeconfig

    def _kubectl_cmd(self) -> list[str]:
        """Build base kubectl command."""
        cmd = ["kubectl"]
        if self.kubeconfig:
            cmd.extend(["--kubeconfig", self.kubeconfig])
        return cmd

    def wait_for_pods_ready(
        self,
        namespace: str,
        timeout_seconds: int = 120,
    ) -> tuple[bool, str]:
        """Wait for all pods in namespace to be ready.

        Args:
            namespace: K8s namespace.
            timeout_seconds: Timeout in seconds.

        Returns:
            Tuple of (success, message).
        """
        try:
            result = subprocess.run(
                self._kubectl_cmd()
                + [
                    "-n",
                    namespace,
                    "wait",
                    "--for=condition=ready",
                    "pod",
                    "--all",
                    f"--timeout={timeout_seconds}s",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return False, f"Pods not ready: {result.stderr}"
            return True, "All pods ready"
        except FileNotFoundError:
            return False, "kubectl not found"
        except Exception as e:
            return False, str(e)

    def get_pod_status(self, namespace: str) -> list[dict[str, str]]:
        """Get status of all pods in namespace.

        Args:
            namespace: K8s namespace.

        Returns:
            List of pod status dicts.
        """
        try:
            result = subprocess.run(
                self._kubectl_cmd()
                + [
                    "-n",
                    namespace,
                    "get",
                    "pods",
                    "-o",
                    "jsonpath={range .items[*]}{.metadata.name},{.status.phase}\\n{end}",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return []

            pods = []
            for line in result.stdout.strip().split("\n"):
                if "," in line:
                    name, phase = line.split(",", 1)
                    pods.append({"name": name, "phase": phase})
            return pods
        except Exception:
            return []
