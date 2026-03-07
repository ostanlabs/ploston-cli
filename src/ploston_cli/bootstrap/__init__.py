"""Bootstrap package for deploying Ploston Control Plane.

This package provides the `ploston bootstrap` command which:
1. Detects Docker/K8s prerequisites
2. Generates docker-compose.yaml or K8s manifests
3. Deploys the Control Plane stack
4. Waits for CP health
5. Optionally chains to `ploston init --import`
"""

from .asset_manager import AssetManager
from .builder import BuildError, build_from_source
from .compose import ComposeConfig, ComposeGenerator, VolumeManager
from .health import HealthCheckResult, HealthPoller
from .image_resolver import ImageConfig, ImageResolverError, resolve_images
from .integration import AutoChainDetector, AutoChainResult, ImportHandoff, RunnerAutoStart
from .k8s import K8sConfig, K8sHealthCheck, K8sIngressHost, K8sManifestGenerator, KubectlDeployer
from .network import NetworkConflict, NetworkConflictAction, NetworkInfo, NetworkManager
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
from .stack import ServiceInfo, StackManager, StackState, StackStatus
from .state import BootstrapAction, BootstrapState, BootstrapStateManager
from .workspace import detect_meta_repo_root

__all__ = [
    # Asset management
    "AssetManager",
    # Image resolution & building
    "ImageConfig",
    "ImageResolverError",
    "resolve_images",
    "BuildError",
    "build_from_source",
    "detect_meta_repo_root",
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
    "ServiceInfo",
    "StackManager",
    "StackState",
    "StackStatus",
    # State management
    "BootstrapAction",
    "BootstrapState",
    "BootstrapStateManager",
    # Network management
    "NetworkManager",
    "NetworkConflict",
    "NetworkConflictAction",
    "NetworkInfo",
    # Init integration
    "AutoChainDetector",
    "AutoChainResult",
    "ImportHandoff",
    "RunnerAutoStart",
    # Kubernetes
    "K8sConfig",
    "K8sIngressHost",
    "K8sManifestGenerator",
    "KubectlDeployer",
    "K8sHealthCheck",
]
