"""Tests for Phase 2: Image Resolution, Workspace Detection, and Builder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ploston_cli.bootstrap.builder import BuildError, _docker_build, build_from_source
from ploston_cli.bootstrap.image_resolver import (
    DEFAULT_PRE_RELEASE_TAG,
    DEFAULT_REGISTRY,
    DEFAULT_RELEASE_TAG,
    DEV_NATIVE_TOOLS,
    DEV_PLOSTON,
    LOCAL_TAG,
    RELEASE_NATIVE_TOOLS,
    RELEASE_PLOSTON,
    ImageConfig,
    ImageResolverError,
    resolve_images,
)
from ploston_cli.bootstrap.workspace import detect_meta_repo_root

# ── ImageConfig tests ──


class TestImageConfig:
    """Tests for ImageConfig dataclass."""

    def test_ploston_tag_extraction(self):
        config = ImageConfig(
            ploston_image="ghcr.io/ostanlabs/ploston:v1.0.0", native_tools_image="x:y"
        )
        assert config.ploston_tag == "v1.0.0"

    def test_ploston_tag_no_colon(self):
        config = ImageConfig(ploston_image="ploston", native_tools_image="x:y")
        assert config.ploston_tag == "latest"

    def test_defaults(self):
        config = ImageConfig(ploston_image="a:b", native_tools_image="c:d")
        assert config.build_from_source is False
        assert config.should_pull is True

    def test_frozen(self):
        config = ImageConfig(ploston_image="a:b", native_tools_image="c:d")
        with pytest.raises(AttributeError):
            config.ploston_image = "new"  # type: ignore[misc]


# ── resolve_images tests ──


class TestResolveImages:
    """Tests for the image resolution matrix."""

    def test_default_release(self):
        config = resolve_images()
        assert config.ploston_image == f"{DEFAULT_REGISTRY}/{RELEASE_PLOSTON}:{DEFAULT_RELEASE_TAG}"
        assert (
            config.native_tools_image
            == f"{DEFAULT_REGISTRY}/{RELEASE_NATIVE_TOOLS}:{DEFAULT_RELEASE_TAG}"
        )
        assert config.should_pull is True
        assert config.build_from_source is False

    def test_explicit_tag(self):
        config = resolve_images(image_tag="v1.2.3")
        assert config.ploston_image == f"{DEFAULT_REGISTRY}/{RELEASE_PLOSTON}:v1.2.3"
        assert config.native_tools_image == f"{DEFAULT_REGISTRY}/{RELEASE_NATIVE_TOOLS}:v1.2.3"

    def test_pre_release_default_tag(self):
        config = resolve_images(pre_release=True)
        assert config.ploston_image == f"{DEFAULT_REGISTRY}/{DEV_PLOSTON}:{DEFAULT_PRE_RELEASE_TAG}"
        assert (
            config.native_tools_image
            == f"{DEFAULT_REGISTRY}/{DEV_NATIVE_TOOLS}:{DEFAULT_PRE_RELEASE_TAG}"
        )

    def test_pre_release_explicit_tag(self):
        config = resolve_images(pre_release=True, image_tag="sha-abc1234")
        assert config.ploston_image == f"{DEFAULT_REGISTRY}/{DEV_PLOSTON}:sha-abc1234"

    def test_build_from_source(self):
        config = resolve_images(build_from_source=True)
        assert config.ploston_image == f"{RELEASE_PLOSTON}:{LOCAL_TAG}"
        assert config.native_tools_image == f"{RELEASE_NATIVE_TOOLS}:{LOCAL_TAG}"
        assert config.build_from_source is True
        assert config.should_pull is False

    def test_build_from_source_with_tag_raises(self):
        with pytest.raises(ImageResolverError, match="mutually exclusive"):
            resolve_images(build_from_source=True, image_tag="v1.0.0")

    def test_build_from_source_with_pre_release_raises(self):
        with pytest.raises(ImageResolverError, match="mutually exclusive"):
            resolve_images(build_from_source=True, pre_release=True)


# ── detect_meta_repo_root tests ──


class TestDetectMetaRepoRoot:
    """Tests for workspace detection."""

    def test_detects_meta_repo(self, tmp_path: Path):
        """Should find root when markers exist."""
        (tmp_path / "packages" / "ploston").mkdir(parents=True)
        (tmp_path / "ci").mkdir()
        (tmp_path / "ci" / "images.yaml").write_text("images: {}")

        # Start from a subdirectory
        subdir = tmp_path / "packages" / "ploston"
        result = detect_meta_repo_root(start=subdir)
        assert result == tmp_path

    def test_returns_none_when_not_in_repo(self, tmp_path: Path):
        """Should return None when markers don't exist."""
        result = detect_meta_repo_root(start=tmp_path)
        assert result is None

    def test_partial_markers_not_detected(self, tmp_path: Path):
        """Should not detect if only one marker exists."""
        (tmp_path / "packages" / "ploston").mkdir(parents=True)
        # Missing ci/images.yaml
        result = detect_meta_repo_root(start=tmp_path)
        assert result is None

    def test_detects_from_root_itself(self, tmp_path: Path):
        """Should detect when starting at the root."""
        (tmp_path / "packages" / "ploston").mkdir(parents=True)
        (tmp_path / "ci").mkdir()
        (tmp_path / "ci" / "images.yaml").write_text("images: {}")

        result = detect_meta_repo_root(start=tmp_path)
        assert result == tmp_path


# ── build_from_source tests ──


class TestBuildFromSource:
    """Tests for the builder module."""

    @patch("ploston_cli.bootstrap.builder.subprocess.run")
    def test_build_success(self, mock_run, tmp_path: Path):
        mock_run.return_value = type("Result", (), {"returncode": 0, "stderr": ""})()
        ploston_img, native_img = build_from_source(tmp_path)
        assert ploston_img == f"{RELEASE_PLOSTON}:{LOCAL_TAG}"
        assert native_img == f"{RELEASE_NATIVE_TOOLS}:{LOCAL_TAG}"
        assert mock_run.call_count == 2

    @patch("ploston_cli.bootstrap.builder.subprocess.run")
    def test_build_failure_raises(self, mock_run, tmp_path: Path):
        mock_run.return_value = type("Result", (), {"returncode": 1, "stderr": "build error"})()
        with pytest.raises(BuildError, match="Failed to build"):
            build_from_source(tmp_path)

    @patch("ploston_cli.bootstrap.builder.subprocess.run")
    def test_docker_build_passes_build_args(self, mock_run, tmp_path: Path):
        mock_run.return_value = type("Result", (), {"returncode": 0, "stderr": ""})()
        _docker_build(
            dockerfile=tmp_path / "Dockerfile",
            context=tmp_path,
            tag="test:latest",
            build_args={"INSTALL_SOURCE": "local"},
        )
        cmd = mock_run.call_args[0][0]
        assert "--build-arg" in cmd
        assert "INSTALL_SOURCE=local" in cmd
