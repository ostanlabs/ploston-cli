"""Unit tests for bootstrap k8s module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from ploston_cli.bootstrap import (
    K8sConfig,
    K8sHealthCheck,
    K8sManifestGenerator,
    KubectlDeployer,
)


class TestK8sConfig:
    """Tests for K8sConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = K8sConfig()
        assert config.namespace == "ploston"
        assert config.tag == "latest"
        assert config.port == 8082
        assert config.registry == "ghcr.io/ostanlabs"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = K8sConfig(
            namespace="custom-ns",
            tag="v1.0.0",
            port=9000,
        )
        assert config.namespace == "custom-ns"
        assert config.tag == "v1.0.0"
        assert config.port == 9000


class TestK8sManifestGenerator:
    """Tests for K8sManifestGenerator."""

    def test_generate_manifests(self):
        """Test generating K8s manifests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir))
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            assert manifest_dir.exists()
            assert (manifest_dir / "namespace.yaml").exists()
            assert (manifest_dir / "redis.yaml").exists()
            assert (manifest_dir / "native-tools.yaml").exists()
            assert (manifest_dir / "ploston.yaml").exists()

    def test_namespace_manifest(self):
        """Test namespace manifest content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir), namespace="test-ns")
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            ns_file = manifest_dir / "namespace.yaml"
            content = yaml.safe_load(ns_file.read_text())

            assert content["kind"] == "Namespace"
            assert content["metadata"]["name"] == "test-ns"

    def test_ploston_deployment(self):
        """Test ploston deployment manifest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir), tag="v1.0.0")
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            ploston_file = manifest_dir / "ploston.yaml"
            docs = list(yaml.safe_load_all(ploston_file.read_text()))

            # Find deployment
            deployment = next(d for d in docs if d["kind"] == "Deployment")
            container = deployment["spec"]["template"]["spec"]["containers"][0]

            assert "v1.0.0" in container["image"]

    def test_service_manifest(self):
        """Test service manifest content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir), port=9000)
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            ploston_file = manifest_dir / "ploston.yaml"
            docs = list(yaml.safe_load_all(ploston_file.read_text()))

            # Find service
            service = next(d for d in docs if d["kind"] == "Service")
            port = service["spec"]["ports"][0]

            assert port["port"] == 9000


class TestKubectlDeployer:
    """Tests for KubectlDeployer."""

    def test_apply_success(self):
        """Test successful manifest application."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_dir = Path(tmpdir)
            (manifest_dir / "test.yaml").write_text("apiVersion: v1\nkind: Namespace")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                deployer = KubectlDeployer()
                success, msg = deployer.apply(manifest_dir)

                assert success is True

    def test_apply_failure(self):
        """Test failed manifest application."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_dir = Path(tmpdir)
            (manifest_dir / "test.yaml").write_text("apiVersion: v1\nkind: Namespace")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stderr="Error applying manifests",
                )
                deployer = KubectlDeployer()
                success, msg = deployer.apply(manifest_dir)

                assert success is False

    def test_delete_namespace(self):
        """Test namespace deletion."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            deployer = KubectlDeployer()
            success, msg = deployer.delete_namespace("test-ns")

            assert success is True


class TestK8sHealthCheck:
    """Tests for K8sHealthCheck."""

    def test_get_pod_status(self):
        """Test getting pod status."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="ploston-abc123,Running\nredis-xyz789,Running\n",
            )
            checker = K8sHealthCheck()
            pods = checker.get_pod_status("ploston")

            assert len(pods) == 2
            assert pods[0]["name"] == "ploston-abc123"
            assert pods[0]["phase"] == "Running"
