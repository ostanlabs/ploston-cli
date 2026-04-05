"""Image resolution for bootstrap deployments.

Resolves Docker image references based on CLI flags:
- Default:              ghcr.io/ostanlabs/ploston:latest (public release)
- --edge:               ghcr.io/ostanlabs/ploston-dev:edge (latest tested dev)
- --edge --image-tag T: ghcr.io/ostanlabs/ploston-dev:T
- --image-tag T:        ghcr.io/ostanlabs/ploston:T (specific release tag)
- --build-from-source:  ploston:local (built locally, no registry)
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

# Registry and image name constants
DEFAULT_REGISTRY = "ghcr.io/ostanlabs"

# Release image names (public)
RELEASE_PLOSTON = "ploston"
RELEASE_NATIVE_TOOLS = "native-tools"

# Dev image names (private, edge builds)
DEV_PLOSTON = "ploston-dev"
DEV_NATIVE_TOOLS = "native-tools-dev"

# Default tags
DEFAULT_RELEASE_TAG = "latest"
DEFAULT_EDGE_TAG = "edge"  # tag applied to latest tested cascade build
LOCAL_TAG = "local"

# Backward compat alias — remove in a future version
DEFAULT_PRE_RELEASE_TAG = DEFAULT_EDGE_TAG


@dataclass(frozen=True)
class ImageConfig:
    """Resolved image references for a bootstrap deployment."""

    ploston_image: str
    native_tools_image: str
    # Whether images need to be built locally
    build_from_source: bool = False
    # Whether images should be pulled (False for local builds)
    should_pull: bool = True

    @property
    def ploston_tag(self) -> str:
        """Extract tag from ploston image reference."""
        return self.ploston_image.rsplit(":", 1)[-1] if ":" in self.ploston_image else "latest"


class ImageResolverError(Exception):
    """Raised when image resolution fails."""


def resolve_images(
    *,
    image_tag: str | None = None,
    edge: bool = False,
    pre_release: bool = False,  # deprecated alias — remove in a future version
    build_from_source: bool = False,
) -> ImageConfig:
    """Resolve Docker image references based on CLI flags.

    Args:
        image_tag: Explicit image tag (e.g., "v1.0.0", "sha-abc1234").
        edge: Use dev registry (ploston-dev, native-tools-dev).
        pre_release: Deprecated alias for ``edge``. Will be removed.
        build_from_source: Build from local source (no registry prefix).

    Returns:
        ImageConfig with resolved image references.

    Raises:
        ImageResolverError: If flags are mutually exclusive.
    """
    # Backward compat: --pre-release was renamed to --edge
    if pre_release and not edge:
        warnings.warn(
            "--pre-release / pre_release=True is deprecated. Use edge=True or --edge.",
            DeprecationWarning,
            stacklevel=2,
        )
        edge = True

    # Validate mutual exclusivity
    if build_from_source and (image_tag is not None or edge):
        raise ImageResolverError(
            "--build-from-source is mutually exclusive with --image-tag and --edge"
        )

    if build_from_source:
        return ImageConfig(
            ploston_image=f"{RELEASE_PLOSTON}:{LOCAL_TAG}",
            native_tools_image=f"{RELEASE_NATIVE_TOOLS}:{LOCAL_TAG}",
            build_from_source=True,
            should_pull=False,
        )

    if edge:
        tag = image_tag or DEFAULT_EDGE_TAG
        return ImageConfig(
            ploston_image=f"{DEFAULT_REGISTRY}/{DEV_PLOSTON}:{tag}",
            native_tools_image=f"{DEFAULT_REGISTRY}/{DEV_NATIVE_TOOLS}:{tag}",
        )

    # Default: release registry
    tag = image_tag or DEFAULT_RELEASE_TAG
    return ImageConfig(
        ploston_image=f"{DEFAULT_REGISTRY}/{RELEASE_PLOSTON}:{tag}",
        native_tools_image=f"{DEFAULT_REGISTRY}/{RELEASE_NATIVE_TOOLS}:{tag}",
    )
