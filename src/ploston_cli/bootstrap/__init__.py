"""Bootstrap package for deploying Ploston Control Plane.

This package provides the `ploston bootstrap` command which:
1. Detects Docker/K8s prerequisites
2. Generates docker-compose.yaml or K8s manifests
3. Deploys the Control Plane stack
4. Waits for CP health
5. Optionally chains to `ploston init --import`
"""

from .compose import ComposeConfig, ComposeGenerator, VolumeManager
from .health import HealthCheckResult, HealthPoller
from .integration import AutoChainDetector, AutoChainResult, ImportHandoff, RunnerAutoStart
from .k8s import K8sConfig, K8sHealthCheck, K8sManifestGenerator, KubectlDeployer
from .prerequisites import (
    DockerDetector,
    DockerInfo,
    ImageResolution,
    ImageResolver,
    KubectlDetector,
    KubectlInfo,
    PortScanner,
    PortStatus,
)
from .stack import StackManager, StackState, StackStatus
from .state import BootstrapAction, BootstrapState, BootstrapStateManager

__all__ = [
    # Prerequisites
    "DockerDetector",
    "DockerInfo",
    "PortScanner",
    "PortStatus",
    "ImageResolver",
    "ImageResolution",
    "KubectlDetector",
    "KubectlInfo",
    # Compose generation
    "ComposeConfig",
    "ComposeGenerator",
    "VolumeManager",
    # Health polling
    "HealthPoller",
    "HealthCheckResult",
    # Stack management
    "StackManager",
    "StackState",
    "StackStatus",
    # State management
    "BootstrapAction",
    "BootstrapState",
    "BootstrapStateManager",
    # Init integration
    "AutoChainDetector",
    "AutoChainResult",
    "ImportHandoff",
    "RunnerAutoStart",
    # Kubernetes
    "K8sConfig",
    "K8sManifestGenerator",
    "KubectlDeployer",
    "K8sHealthCheck",
]
