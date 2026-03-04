"""Build Docker images from local source.

Used by `ploston bootstrap --build-from-source` to build ploston and
native-tools images from the local meta-repo checkout.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .image_resolver import LOCAL_TAG, RELEASE_NATIVE_TOOLS, RELEASE_PLOSTON


class BuildError(Exception):
    """Raised when a Docker build fails."""


def build_from_source(repo_root: Path) -> tuple[str, str]:
    """Build ploston and native-tools images from local source.

    Uses the consolidated Dockerfiles with INSTALL_SOURCE=local build arg.

    Args:
        repo_root: Path to the meta-repo root (agent-execution-layer).

    Returns:
        Tuple of (ploston_image, native_tools_image) tags.

    Raises:
        BuildError: If any build fails.
    """
    ploston_tag = f"{RELEASE_PLOSTON}:{LOCAL_TAG}"
    native_tools_tag = f"{RELEASE_NATIVE_TOOLS}:{LOCAL_TAG}"

    # Build ploston image
    _docker_build(
        dockerfile=repo_root / "packages" / "ploston" / "Dockerfile",
        context=repo_root,
        tag=ploston_tag,
        build_args={"INSTALL_SOURCE": "local"},
    )

    # Build native-tools image
    _docker_build(
        dockerfile=repo_root / "packages" / "ploston" / "docker" / "native-tools" / "Dockerfile",
        context=repo_root,
        tag=native_tools_tag,
        build_args={"INSTALL_SOURCE": "local"},
    )

    return ploston_tag, native_tools_tag


def _docker_build(
    dockerfile: Path,
    context: Path,
    tag: str,
    build_args: dict[str, str] | None = None,
) -> None:
    """Run docker build.

    Args:
        dockerfile: Path to the Dockerfile.
        context: Build context directory.
        tag: Image tag.
        build_args: Optional build arguments.

    Raises:
        BuildError: If the build fails.
    """
    cmd = ["docker", "build", "-f", str(dockerfile), "-t", tag]

    for key, value in (build_args or {}).items():
        cmd.extend(["--build-arg", f"{key}={value}"])

    cmd.append(str(context))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise BuildError(f"Failed to build {tag}:\n{result.stderr}")
