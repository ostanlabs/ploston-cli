"""Unit tests for bootstrap k8s module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from ploston_cli.bootstrap import (
    K8sConfig,
    K8sHealthCheck,
    K8sIngressHost,
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
        assert config.port == 8022
        assert config.metrics_port == 9090
        assert config.registry == "ghcr.io/ostanlabs"
        assert config.native_tools_enabled is False
        assert config.config_content == ""
        assert config.redis_persistence_enabled is False
        assert config.redis_persistence_size == "1Gi"

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

    def test_generate_manifests_default(self):
        """Test generating K8s manifests with defaults (native-tools disabled)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir))
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            assert manifest_dir.exists()
            assert (manifest_dir / "namespace.yaml").exists()
            assert (manifest_dir / "redis.yaml").exists()
            assert (manifest_dir / "ploston.yaml").exists()
            # native-tools disabled by default
            assert not (manifest_dir / "native-tools.yaml").exists()

    def test_generate_manifests_with_native_tools(self):
        """Test generating K8s manifests with native-tools enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir), native_tools_enabled=True)
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            assert (manifest_dir / "native-tools.yaml").exists()

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

            deployment = next(d for d in docs if d["kind"] == "Deployment")
            container = deployment["spec"]["template"]["spec"]["containers"][0]

            assert "v1.0.0" in container["image"]

    def test_service_manifest(self):
        """Test service manifest has http and metrics ports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir), port=9000, metrics_port=9090)
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            ploston_file = manifest_dir / "ploston.yaml"
            docs = list(yaml.safe_load_all(ploston_file.read_text()))

            service = next(d for d in docs if d["kind"] == "Service")
            ports = {p["name"]: p for p in service["spec"]["ports"]}

            assert ports["http"]["port"] == 9000
            assert ports["metrics"]["port"] == 9090

    def test_full_image_override_ploston(self):
        """Test ploston deployment uses full image reference when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(
                output_dir=Path(tmpdir),
                ploston_image_full="ghcr.io/ostanlabs/ploston:v2.0.0",
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            ploston_file = manifest_dir / "ploston.yaml"
            docs = list(yaml.safe_load_all(ploston_file.read_text()))
            deployment = next(d for d in docs if d["kind"] == "Deployment")
            container = deployment["spec"]["template"]["spec"]["containers"][0]

            assert container["image"] == "ghcr.io/ostanlabs/ploston:v2.0.0"

    def test_full_image_override_native_tools(self):
        """Test native-tools deployment uses full image reference when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(
                output_dir=Path(tmpdir),
                native_tools_enabled=True,
                native_tools_image_full="ghcr.io/ostanlabs/native-tools-dev:edge",
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            nt_file = manifest_dir / "native-tools.yaml"
            docs = list(yaml.safe_load_all(nt_file.read_text()))
            deployment = next(d for d in docs if d["kind"] == "Deployment")
            container = deployment["spec"]["template"]["spec"]["containers"][0]

            assert container["image"] == "ghcr.io/ostanlabs/native-tools-dev:edge"

    def test_full_image_overrides_both(self):
        """Test both images use full references when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(
                output_dir=Path(tmpdir),
                native_tools_enabled=True,
                ploston_image_full="ploston:local",
                native_tools_image_full="native-tools:local",
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            # Check ploston
            ploston_file = manifest_dir / "ploston.yaml"
            docs = list(yaml.safe_load_all(ploston_file.read_text()))
            deployment = next(d for d in docs if d["kind"] == "Deployment")
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            assert container["image"] == "ploston:local"

            # Check native-tools
            nt_file = manifest_dir / "native-tools.yaml"
            docs = list(yaml.safe_load_all(nt_file.read_text()))
            deployment = next(d for d in docs if d["kind"] == "Deployment")
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            assert container["image"] == "native-tools:local"

    def test_fallback_to_registry_tag(self):
        """Test fallback to registry/name:tag when no full override."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir), tag="sha-abc1234")
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            ploston_file = manifest_dir / "ploston.yaml"
            docs = list(yaml.safe_load_all(ploston_file.read_text()))
            deployment = next(d for d in docs if d["kind"] == "Deployment")
            container = deployment["spec"]["template"]["spec"]["containers"][0]

            assert container["image"] == "ghcr.io/ostanlabs/ploston-dev:sha-abc1234"


class TestK8sIngress:
    """Tests for Ingress manifest generation."""

    def test_no_ingress_by_default(self):
        """Test that no ingress.yaml is generated when ingress is disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir))
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            assert not (manifest_dir / "ingress.yaml").exists()

    def test_ingress_generated_when_enabled(self):
        """Test that ingress.yaml is generated when ingress is enabled with hosts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(
                output_dir=Path(tmpdir),
                ingress_enabled=True,
                ingress_hosts=[K8sIngressHost(host="ploston.example.com")],
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            assert (manifest_dir / "ingress.yaml").exists()

    def test_ingress_not_generated_without_hosts(self):
        """Test that ingress.yaml is NOT generated when enabled but no hosts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir), ingress_enabled=True)
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            assert not (manifest_dir / "ingress.yaml").exists()

    def test_ingress_api_version_and_kind(self):
        """Test ingress manifest has correct apiVersion and kind."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(
                output_dir=Path(tmpdir),
                ingress_enabled=True,
                ingress_hosts=[K8sIngressHost(host="ploston.example.com")],
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            docs = list(yaml.safe_load_all((manifest_dir / "ingress.yaml").read_text()))
            ingress = docs[0]
            assert ingress["apiVersion"] == "networking.k8s.io/v1"
            assert ingress["kind"] == "Ingress"

    def test_ingress_namespace(self):
        """Test ingress is created in the correct namespace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(
                output_dir=Path(tmpdir),
                namespace="test-ns",
                ingress_enabled=True,
                ingress_hosts=[K8sIngressHost(host="ploston.example.com")],
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            docs = list(yaml.safe_load_all((manifest_dir / "ingress.yaml").read_text()))
            assert docs[0]["metadata"]["namespace"] == "test-ns"

    def test_ingress_class_name(self):
        """Test ingress class name is set when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(
                output_dir=Path(tmpdir),
                ingress_enabled=True,
                ingress_class_name="traefik",
                ingress_hosts=[K8sIngressHost(host="ploston.example.com")],
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            docs = list(yaml.safe_load_all((manifest_dir / "ingress.yaml").read_text()))
            assert docs[0]["spec"]["ingressClassName"] == "traefik"

    def test_ingress_no_class_name_when_not_set(self):
        """Test ingressClassName is omitted when not provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(
                output_dir=Path(tmpdir),
                ingress_enabled=True,
                ingress_hosts=[K8sIngressHost(host="ploston.example.com")],
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            docs = list(yaml.safe_load_all((manifest_dir / "ingress.yaml").read_text()))
            assert "ingressClassName" not in docs[0]["spec"]

    def test_ingress_annotations(self):
        """Test ingress annotations are set when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(
                output_dir=Path(tmpdir),
                ingress_enabled=True,
                ingress_annotations={
                    "traefik.ingress.kubernetes.io/router.entrypoints": "web",
                },
                ingress_hosts=[K8sIngressHost(host="ploston.example.com")],
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            docs = list(yaml.safe_load_all((manifest_dir / "ingress.yaml").read_text()))
            annotations = docs[0]["metadata"]["annotations"]
            assert annotations["traefik.ingress.kubernetes.io/router.entrypoints"] == "web"

    def test_ingress_no_annotations_when_empty(self):
        """Test annotations key is omitted when no annotations provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(
                output_dir=Path(tmpdir),
                ingress_enabled=True,
                ingress_hosts=[K8sIngressHost(host="ploston.example.com")],
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            docs = list(yaml.safe_load_all((manifest_dir / "ingress.yaml").read_text()))
            assert "annotations" not in docs[0]["metadata"]

    def test_ingress_host_rule(self):
        """Test ingress host rule is correctly structured."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(
                output_dir=Path(tmpdir),
                port=8022,
                ingress_enabled=True,
                ingress_hosts=[K8sIngressHost(host="ploston.example.com")],
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            docs = list(yaml.safe_load_all((manifest_dir / "ingress.yaml").read_text()))
            rules = docs[0]["spec"]["rules"]
            assert len(rules) == 1
            rule = rules[0]
            assert rule["host"] == "ploston.example.com"
            path = rule["http"]["paths"][0]
            assert path["path"] == "/"
            assert path["pathType"] == "Prefix"
            assert path["backend"]["service"]["name"] == "ploston"
            assert path["backend"]["service"]["port"]["number"] == 8022

    def test_ingress_multiple_hosts(self):
        """Test ingress with multiple host rules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(
                output_dir=Path(tmpdir),
                ingress_enabled=True,
                ingress_hosts=[
                    K8sIngressHost(host="ploston.example.com"),
                    K8sIngressHost(host="ploston.internal.local", path="/api"),
                ],
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            docs = list(yaml.safe_load_all((manifest_dir / "ingress.yaml").read_text()))
            rules = docs[0]["spec"]["rules"]
            assert len(rules) == 2
            assert rules[0]["host"] == "ploston.example.com"
            assert rules[0]["http"]["paths"][0]["path"] == "/"
            assert rules[1]["host"] == "ploston.internal.local"
            assert rules[1]["http"]["paths"][0]["path"] == "/api"


class TestK8sDomainIngress:
    """Tests for domain-based ingress (simulates --domain CLI flag)."""

    def test_domain_generates_namespace_dot_domain_host(self):
        """Test that domain + namespace produces <namespace>.<domain> host."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Simulates: ploston bootstrap --target k8s --domain ostanlabs.homelab --namespace ploston
            domain = "ostanlabs.homelab"
            ns = "ploston"
            config = K8sConfig(
                output_dir=Path(tmpdir),
                namespace=ns,
                ingress_enabled=True,
                ingress_hosts=[K8sIngressHost(host=f"{ns}.{domain}")],
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            docs = list(yaml.safe_load_all((manifest_dir / "ingress.yaml").read_text()))
            rules = docs[0]["spec"]["rules"]
            assert len(rules) == 1
            assert rules[0]["host"] == "ploston.ostanlabs.homelab"

    def test_domain_with_custom_namespace(self):
        """Test domain with non-default namespace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            domain = "example.com"
            ns = "staging"
            config = K8sConfig(
                output_dir=Path(tmpdir),
                namespace=ns,
                ingress_enabled=True,
                ingress_hosts=[K8sIngressHost(host=f"{ns}.{domain}")],
            )
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            docs = list(yaml.safe_load_all((manifest_dir / "ingress.yaml").read_text()))
            assert docs[0]["spec"]["rules"][0]["host"] == "staging.example.com"

    def test_no_domain_no_ingress(self):
        """Test that without domain, no ingress is generated (default)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir))
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)
            assert not (manifest_dir / "ingress.yaml").exists()


class TestK8sLabels:
    """Tests for app.kubernetes.io/* labels on all resources."""

    def _generate(self, **kwargs):
        """Helper to generate manifests and return all docs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir), native_tools_enabled=True, **kwargs)
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)
            all_docs = []
            for f in sorted(manifest_dir.glob("*.yaml")):
                all_docs.extend(yaml.safe_load_all(f.read_text()))
            return all_docs

    def test_all_resources_have_labels(self):
        """Every resource must have app.kubernetes.io/name and component labels."""
        docs = self._generate()
        for doc in docs:
            labels = doc["metadata"].get("labels", {})
            assert "app.kubernetes.io/name" in labels, (
                f"{doc['kind']} {doc['metadata']['name']} missing name label"
            )
            assert "app.kubernetes.io/component" in labels, (
                f"{doc['kind']} {doc['metadata']['name']} missing component label"
            )
            assert labels["app.kubernetes.io/name"] == "ploston"

    def test_instance_label_matches_namespace(self):
        """Instance label should match the namespace."""
        docs = self._generate(namespace="my-ns")
        for doc in docs:
            labels = doc["metadata"].get("labels", {})
            assert labels["app.kubernetes.io/instance"] == "my-ns"

    def test_deployment_selectors_use_standard_labels(self):
        """Deployment selectors should use app.kubernetes.io/* labels."""
        docs = self._generate()
        deployments = [d for d in docs if d["kind"] == "Deployment"]
        for dep in deployments:
            selector = dep["spec"]["selector"]["matchLabels"]
            assert "app.kubernetes.io/name" in selector
            assert "app.kubernetes.io/component" in selector


class TestK8sNativeToolsToggle:
    """Tests for native-tools enable/disable."""

    def test_disabled_by_default(self):
        """Native-tools should not be generated by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir))
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            assert not (manifest_dir / "native-tools.yaml").exists()

    def test_no_native_tools_url_when_disabled(self):
        """Ploston deployment should not have NATIVE_TOOLS_URL when native-tools disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir))
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            docs = list(yaml.safe_load_all((manifest_dir / "ploston.yaml").read_text()))
            deployment = next(d for d in docs if d["kind"] == "Deployment")
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            env_names = [e["name"] for e in container["env"]]
            assert "NATIVE_TOOLS_URL" not in env_names

    def test_native_tools_url_when_enabled(self):
        """Ploston deployment should have NATIVE_TOOLS_URL when native-tools enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir), native_tools_enabled=True)
            generator = K8sManifestGenerator()
            manifest_dir = generator.generate(config)

            docs = list(yaml.safe_load_all((manifest_dir / "ploston.yaml").read_text()))
            deployment = next(d for d in docs if d["kind"] == "Deployment")
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            env_map = {e["name"]: e["value"] for e in container["env"]}
            assert env_map["NATIVE_TOOLS_URL"] == "http://native-tools:8081"

    def test_stale_native_tools_removed(self):
        """Re-generating with native-tools disabled should remove stale manifest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            generator = K8sManifestGenerator()
            # First generate with native-tools enabled
            config_on = K8sConfig(output_dir=Path(tmpdir), native_tools_enabled=True)
            generator.generate(config_on)
            assert (Path(tmpdir) / "native-tools.yaml").exists()
            # Then regenerate with disabled
            config_off = K8sConfig(output_dir=Path(tmpdir), native_tools_enabled=False)
            generator.generate(config_off)
            assert not (Path(tmpdir) / "native-tools.yaml").exists()


class TestK8sConfigMap:
    """Tests for ConfigMap (config file injection)."""

    def test_configmap_generated(self):
        """ConfigMap for ploston-config.yaml should always be generated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir))
            generator = K8sManifestGenerator()
            generator.generate(config)

            docs = list(yaml.safe_load_all((Path(tmpdir) / "ploston.yaml").read_text()))
            cm = next(d for d in docs if d["kind"] == "ConfigMap")
            assert cm["metadata"]["name"] == "ploston-config"
            # Empty content = CONFIGURATION mode
            assert cm["data"]["ploston-config.yaml"] == ""

    def test_configmap_with_content(self):
        """ConfigMap should contain provided config content."""
        content = (
            "tools:\n  mcp_servers:\n    native-tools:\n      url: http://native-tools:8081/mcp\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir), config_content=content)
            generator = K8sManifestGenerator()
            generator.generate(config)

            docs = list(yaml.safe_load_all((Path(tmpdir) / "ploston.yaml").read_text()))
            cm = next(d for d in docs if d["kind"] == "ConfigMap")
            assert cm["data"]["ploston-config.yaml"] == content

    def test_volume_mount_present(self):
        """Ploston container should mount config volume."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir))
            generator = K8sManifestGenerator()
            generator.generate(config)

            docs = list(yaml.safe_load_all((Path(tmpdir) / "ploston.yaml").read_text()))
            deployment = next(d for d in docs if d["kind"] == "Deployment")
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            mount_paths = [vm["mountPath"] for vm in container["volumeMounts"]]
            assert "/app/config" in mount_paths

    def test_config_path_env(self):
        """Ploston container should have CONFIG_PATH env var."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir))
            generator = K8sManifestGenerator()
            generator.generate(config)

            docs = list(yaml.safe_load_all((Path(tmpdir) / "ploston.yaml").read_text()))
            deployment = next(d for d in docs if d["kind"] == "Deployment")
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            env_map = {e["name"]: e["value"] for e in container["env"]}
            assert env_map["CONFIG_PATH"] == "/app/config/ploston-config.yaml"


class TestK8sRedis:
    """Tests for Redis ConfigMap, PVC, and probes."""

    def _redis_docs(self, **kwargs):
        """Helper to generate and return redis docs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = K8sConfig(output_dir=Path(tmpdir), **kwargs)
            generator = K8sManifestGenerator()
            generator.generate(config)
            return list(yaml.safe_load_all((Path(tmpdir) / "redis.yaml").read_text()))

    def test_redis_configmap_generated(self):
        """Redis ConfigMap with redis.conf should be generated."""
        docs = self._redis_docs()
        cm = next(d for d in docs if d["kind"] == "ConfigMap")
        assert cm["metadata"]["name"] == "ploston-redis-config"
        conf = cm["data"]["redis.conf"]
        assert "appendonly yes" in conf
        assert "maxmemory 128mb" in conf

    def test_redis_uses_configmap(self):
        """Redis container should use redis.conf from ConfigMap."""
        docs = self._redis_docs()
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        assert container["command"] == ["redis-server", "/etc/redis/redis.conf"]
        mount_paths = [vm["mountPath"] for vm in container["volumeMounts"]]
        assert "/etc/redis" in mount_paths

    def test_redis_liveness_probe(self):
        """Redis should have liveness probe."""
        docs = self._redis_docs()
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        assert "livenessProbe" in container
        assert container["livenessProbe"]["exec"]["command"] == ["redis-cli", "ping"]

    def test_redis_readiness_probe(self):
        """Redis should have readiness probe."""
        docs = self._redis_docs()
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        assert "readinessProbe" in container
        assert container["readinessProbe"]["exec"]["command"] == ["redis-cli", "ping"]

    def test_redis_no_pvc_by_default(self):
        """No PVC should be generated by default."""
        docs = self._redis_docs()
        pvcs = [d for d in docs if d["kind"] == "PersistentVolumeClaim"]
        assert len(pvcs) == 0
        # Volume should be emptyDir
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        volumes = deployment["spec"]["template"]["spec"]["volumes"]
        data_vol = next(v for v in volumes if v["name"] == "redis-data")
        assert "emptyDir" in data_vol

    def test_redis_pvc_when_enabled(self):
        """PVC should be generated when persistence is enabled."""
        docs = self._redis_docs(redis_persistence_enabled=True, redis_persistence_size="5Gi")
        pvcs = [d for d in docs if d["kind"] == "PersistentVolumeClaim"]
        assert len(pvcs) == 1
        assert pvcs[0]["spec"]["resources"]["requests"]["storage"] == "5Gi"
        # Volume should reference PVC
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        volumes = deployment["spec"]["template"]["spec"]["volumes"]
        data_vol = next(v for v in volumes if v["name"] == "redis-data")
        assert "persistentVolumeClaim" in data_vol
        assert data_vol["persistentVolumeClaim"]["claimName"] == "ploston-redis-pvc"

    def test_redis_service_named_port(self):
        """Redis service should use named port."""
        docs = self._redis_docs()
        service = next(d for d in docs if d["kind"] == "Service")
        port = service["spec"]["ports"][0]
        assert port["name"] == "redis"
        assert port["port"] == 6379
        assert port["targetPort"] == "redis"


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
