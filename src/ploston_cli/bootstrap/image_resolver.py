"""Image resolution for bootstrap deployments.

Resolves Docker image references based on CLI flags:
- Default: ghcr.io/ostanlabs/ploston:latest (release registry)
- --image-tag TAG: ghcr.io/ostanlabs/ploston:TAG
- --pre-release: ghcr.io/ostanlabs/ploston-dev:edge (dev registry)
- --pre-release --image-tag TAG: ghcr.io/ostanlabs/ploston-dev:TAG
- --build-from-source: ploston:local (no registry, local build)
"""

from __future__ import annotations

from dataclasses import dataclass

# Registry and image name constants
DEFAULT_REGISTRY = "ghcr.io/ostanlabs"

# Release image names (public)
RELEASE_PLOSTON = "ploston"
RELEASE_NATIVE_TOOLS = "native-tools"

# Dev image names (private, pre-release)
DEV_PLOSTON = "ploston-dev"
DEV_NATIVE_TOOLS = "native-tools-dev"

# Default tags
DEFAULT_RELEASE_TAG = "latest"
DEFAULT_PRE_RELEASE_TAG = "edge"
LOCAL_TAG = "local"


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
    pre_release: bool = False,
    build_from_source: bool = False,
) -> ImageConfig:
    """Resolve Docker image references based on CLI flags.

    Args:
        image_tag: Explicit image tag (e.g., "v1.0.0", "sha-abc1234").
        pre_release: Use dev registry (ploston-dev, native-tools-dev).
        build_from_source: Build from local source (no registry prefix).

    Returns:
        ImageConfig with resolved image references.

    Raises:
        ImageResolverError: If flags are mutually exclusive.
    """
    # Validate mutual exclusivity
    if build_from_source and (image_tag is not None or pre_release):
        raise ImageResolverError(
            "--build-from-source is mutually exclusive with --image-tag and --pre-release"
        )

    if build_from_source:
        return ImageConfig(
            ploston_image=f"{RELEASE_PLOSTON}:{LOCAL_TAG}",
            native_tools_image=f"{RELEASE_NATIVE_TOOLS}:{LOCAL_TAG}",
            build_from_source=True,
            should_pull=False,
        )

    if pre_release:
        tag = image_tag or DEFAULT_PRE_RELEASE_TAG
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
