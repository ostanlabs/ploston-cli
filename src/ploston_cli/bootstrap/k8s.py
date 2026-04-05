"""Kubernetes manifest generation for bootstrap command.

This module generates Kubernetes manifests for deploying
the Ploston Control Plane stack to a K8s cluster.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
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
class K8sIngressHost:
    """Ingress host configuration."""

    host: str
    path: str = "/"
    path_type: str = "Prefix"


@dataclass
class K8sConfig:
    """Configuration for K8s deployment."""

    namespace: str = "ploston"
    tag: str = "latest"
    port: int = 8022
    metrics_port: int = 9090
    redis_port: int = 6379
    registry: str = DEFAULT_REGISTRY
    ploston_image: str = DEFAULT_PLOSTON_IMAGE
    native_tools_image: str = DEFAULT_NATIVE_TOOLS_IMAGE
    output_dir: Path | None = None
    # Full image references (override registry/name/tag if set)
    ploston_image_full: str | None = None
    native_tools_image_full: str | None = None
    # Native-tools toggle (disabled by default)
    native_tools_enabled: bool = False
    # Config file content (empty = CONFIGURATION mode)
    config_content: str = ""
    # Redis persistence
    redis_persistence_enabled: bool = False
    redis_persistence_size: str = "1Gi"
    # Ingress configuration
    ingress_enabled: bool = False
    ingress_class_name: str | None = None
    ingress_annotations: dict[str, str] = field(default_factory=dict)
    ingress_hosts: list[K8sIngressHost] = field(default_factory=list)


class K8sManifestGenerator:
    """Generate Kubernetes manifests."""

    def _labels(self, config: K8sConfig, component: str) -> dict[str, str]:
        """Build standard app.kubernetes.io/* labels."""
        return {
            "app.kubernetes.io/name": "ploston",
            "app.kubernetes.io/instance": config.namespace,
            "app.kubernetes.io/component": component,
        }

    def _selector_labels(self, config: K8sConfig, component: str) -> dict[str, str]:
        """Build selector labels (subset of full labels)."""
        return {
            "app.kubernetes.io/name": "ploston",
            "app.kubernetes.io/component": component,
        }

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

        # Generate redis
        self._write_manifest(
            output_dir / "redis.yaml",
            self._build_redis(config),
        )

        # Generate native-tools (if enabled)
        if config.native_tools_enabled:
            self._write_manifest(
                output_dir / "native-tools.yaml",
                self._build_native_tools(config),
            )
        else:
            # Remove stale native-tools manifest if it exists
            nt_path = output_dir / "native-tools.yaml"
            if nt_path.exists():
                nt_path.unlink()

        # Generate ploston
        self._write_manifest(
            output_dir / "ploston.yaml",
            self._build_ploston(config),
        )

        # Generate ingress manifest (if enabled)
        if config.ingress_enabled and config.ingress_hosts:
            self._write_manifest(
                output_dir / "ingress.yaml",
                self._build_ingress(config),
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
                "metadata": {
                    "name": config.namespace,
                    "labels": self._labels(config, "namespace"),
                },
            }
        ]

    def _build_redis(self, config: K8sConfig) -> list[dict[str, Any]]:
        """Build Redis ConfigMap, optional PVC, Deployment, and Service."""
        labels = self._labels(config, "redis")
        selector = self._selector_labels(config, "redis")
        manifests: list[dict[str, Any]] = []

        # Redis ConfigMap
        configmap = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "ploston-redis-config",
                "namespace": config.namespace,
                "labels": labels,
            },
            "data": {
                "redis.conf": (
                    "# Redis configuration for Ploston config store\n"
                    "appendonly yes\n"
                    "maxmemory 128mb\n"
                    "maxmemory-policy allkeys-lru\n"
                    "# Disable persistence snapshots (AOF is sufficient)\n"
                    'save ""\n'
                ),
            },
        }
        manifests.append(configmap)

        # Optional PVC
        if config.redis_persistence_enabled:
            pvc = {
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {
                    "name": "ploston-redis-pvc",
                    "namespace": config.namespace,
                    "labels": labels,
                },
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "resources": {"requests": {"storage": config.redis_persistence_size}},
                },
            }
            manifests.append(pvc)

        # Volume mounts
        volume_mounts = [
            {"name": "redis-config", "mountPath": "/etc/redis"},
            {"name": "redis-data", "mountPath": "/data"},
        ]

        # Volumes
        volumes: list[dict[str, Any]] = [
            {"name": "redis-config", "configMap": {"name": "ploston-redis-config"}},
        ]
        if config.redis_persistence_enabled:
            volumes.append(
                {"name": "redis-data", "persistentVolumeClaim": {"claimName": "ploston-redis-pvc"}}
            )
        else:
            volumes.append({"name": "redis-data", "emptyDir": {}})

        # Deployment
        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "redis",
                "namespace": config.namespace,
                "labels": labels,
            },
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": selector},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "containers": [
                            {
                                "name": "redis",
                                "image": "redis:7-alpine",
                                "command": ["redis-server", "/etc/redis/redis.conf"],
                                "ports": [
                                    {"name": "redis", "containerPort": 6379, "protocol": "TCP"}
                                ],
                                "livenessProbe": {
                                    "exec": {"command": ["redis-cli", "ping"]},
                                    "initialDelaySeconds": 15,
                                    "periodSeconds": 20,
                                },
                                "readinessProbe": {
                                    "exec": {"command": ["redis-cli", "ping"]},
                                    "initialDelaySeconds": 5,
                                    "periodSeconds": 10,
                                },
                                "volumeMounts": volume_mounts,
                            }
                        ],
                        "volumes": volumes,
                    },
                },
            },
        }
        manifests.append(deployment)

        # Service
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "redis",
                "namespace": config.namespace,
                "labels": labels,
            },
            "spec": {
                "selector": selector,
                "ports": [
                    {
                        "name": "redis",
                        "port": config.redis_port,
                        "targetPort": "redis",
                        "protocol": "TCP",
                    }
                ],
            },
        }
        manifests.append(service)

        return manifests

    def _build_native_tools(self, config: K8sConfig) -> list[dict[str, Any]]:
        """Build native-tools deployment and service."""
        labels = self._labels(config, "native-tools")
        selector = self._selector_labels(config, "native-tools")
        image = (
            config.native_tools_image_full
            or f"{config.registry}/{config.native_tools_image}:{config.tag}"
        )

        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "native-tools",
                "namespace": config.namespace,
                "labels": labels,
            },
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": selector},
                "template": {
                    "metadata": {"labels": labels},
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
            "metadata": {
                "name": "native-tools",
                "namespace": config.namespace,
                "labels": labels,
            },
            "spec": {
                "selector": selector,
                "ports": [{"port": 8081, "targetPort": 8081}],
            },
        }

        return [deployment, service]

    def _build_ploston(self, config: K8sConfig) -> list[dict[str, Any]]:
        """Build Ploston CP ConfigMap, Deployment, and Service."""
        labels = self._labels(config, "server")
        selector = self._selector_labels(config, "server")
        image = (
            config.ploston_image_full or f"{config.registry}/{config.ploston_image}:{config.tag}"
        )
        manifests: list[dict[str, Any]] = []

        # ConfigMap for ploston-config.yaml
        configmap = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "ploston-config",
                "namespace": config.namespace,
                "labels": labels,
            },
            "data": {
                "ploston-config.yaml": config.config_content if config.config_content else "",
            },
        }
        manifests.append(configmap)

        # Environment variables
        env: list[dict[str, str]] = [
            {"name": "PLOSTON_HOST", "value": "0.0.0.0"},
            {"name": "PLOSTON_PORT", "value": str(config.port)},
            {"name": "PLOSTON_METRICS_PORT", "value": str(config.metrics_port)},
            {"name": "PLOSTON_REDIS_URL", "value": f"redis://redis:{config.redis_port}/0"},
            {"name": "CONFIG_PATH", "value": "/app/config/ploston-config.yaml"},
        ]
        if config.native_tools_enabled:
            env.append({"name": "NATIVE_TOOLS_URL", "value": "http://native-tools:8081"})

        # Deployment
        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "ploston",
                "namespace": config.namespace,
                "labels": labels,
            },
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": selector},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "containers": [
                            {
                                "name": "ploston",
                                "image": image,
                                "ports": [
                                    {
                                        "name": "http",
                                        "containerPort": config.port,
                                        "protocol": "TCP",
                                    },
                                    {
                                        "name": "metrics",
                                        "containerPort": config.metrics_port,
                                        "protocol": "TCP",
                                    },
                                ],
                                "env": env,
                                "volumeMounts": [
                                    {"name": "config", "mountPath": "/app/config"},
                                ],
                                "readinessProbe": {
                                    "httpGet": {"path": "/health", "port": config.port},
                                    "initialDelaySeconds": 10,
                                    "periodSeconds": 10,
                                },
                                "livenessProbe": {
                                    "httpGet": {"path": "/health", "port": config.port},
                                    "initialDelaySeconds": 30,
                                    "periodSeconds": 30,
                                },
                            }
                        ],
                        "volumes": [
                            {"name": "config", "configMap": {"name": "ploston-config"}},
                        ],
                    },
                },
            },
        }
        manifests.append(deployment)

        # Service
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "ploston",
                "namespace": config.namespace,
                "labels": labels,
            },
            "spec": {
                "selector": selector,
                "ports": [
                    {"name": "http", "port": config.port, "targetPort": "http", "protocol": "TCP"},
                    {
                        "name": "metrics",
                        "port": config.metrics_port,
                        "targetPort": "metrics",
                        "protocol": "TCP",
                    },
                ],
            },
        }
        manifests.append(service)

        return manifests

    def _build_ingress(self, config: K8sConfig) -> list[dict[str, Any]]:
        """Build Ingress manifest for the Ploston service."""
        labels = self._labels(config, "ingress")
        rules = []
        for host_cfg in config.ingress_hosts:
            rules.append(
                {
                    "host": host_cfg.host,
                    "http": {
                        "paths": [
                            {
                                "path": host_cfg.path,
                                "pathType": host_cfg.path_type,
                                "backend": {
                                    "service": {
                                        "name": "ploston",
                                        "port": {"number": config.port},
                                    }
                                },
                            }
                        ]
                    },
                }
            )

        metadata: dict[str, Any] = {
            "name": "ploston",
            "namespace": config.namespace,
            "labels": labels,
        }
        if config.ingress_annotations:
            metadata["annotations"] = config.ingress_annotations

        spec: dict[str, Any] = {"rules": rules}
        if config.ingress_class_name:
            spec["ingressClassName"] = config.ingress_class_name

        ingress = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": metadata,
            "spec": spec,
        }

        return [ingress]


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
