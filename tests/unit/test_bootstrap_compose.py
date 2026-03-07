"""Unit tests for bootstrap compose module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from ploston_cli.bootstrap import AssetManager, ComposeConfig, ComposeGenerator, VolumeManager


class TestComposeConfig:
    """Tests for ComposeConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ComposeConfig()
        assert config.tag == "latest"
        assert config.port == 8022
        assert config.redis_port == 6379
        assert config.with_observability is False

    def test_custom_values(self):
        """Test custom configuration values."""
        config = ComposeConfig(
            tag="v1.0.0",
            port=9000,
            redis_port=6380,
            with_observability=True,
        )
        assert config.tag == "v1.0.0"
        assert config.port == 9000
        assert config.redis_port == 6380
        assert config.with_observability is True


class TestComposeGenerator:
    """Tests for ComposeGenerator."""

    def test_generate_basic_compose(self):
        """Test generating basic docker-compose.yaml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ComposeConfig(output_dir=Path(tmpdir))
            generator = ComposeGenerator()
            compose_file = generator.generate(config)

            assert compose_file.exists()
            content = yaml.safe_load(compose_file.read_text())

            # Check services
            assert "services" in content
            assert "ploston" in content["services"]
            assert "native-tools" in content["services"]
            assert "redis" in content["services"]

    def test_generate_without_observability_services(self):
        """Test that base compose does NOT include observability services.

        Observability services are handled by a separate compose overlay via
        AssetManager. The flag only injects OTEL env vars into the ploston
        service.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ComposeConfig(
                output_dir=Path(tmpdir),
                with_observability=True,
            )
            generator = ComposeGenerator()
            compose_file = generator.generate(config)

            content = yaml.safe_load(compose_file.read_text())

            # Base compose should NOT have observability services
            assert "prometheus" not in content["services"]
            assert "grafana" not in content["services"]
            assert "loki" not in content["services"]
            # Core services should still be present
            assert "ploston" in content["services"]
            assert "redis" in content["services"]
            assert "native-tools" in content["services"]

    def test_observability_injects_otel_env_vars(self):
        """Test that with_observability=True injects OTEL env vars (DEC-149)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ComposeConfig(
                output_dir=Path(tmpdir),
                with_observability=True,
            )
            generator = ComposeGenerator()
            compose_file = generator.generate(config)

            content = yaml.safe_load(compose_file.read_text())
            env = content["services"]["ploston"]["environment"]
            assert env["PLOSTON_LOGS_ENABLED"] == "true"
            assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://otel-collector:4317"
            assert env["OTEL_EXPORTER_OTLP_INSECURE"] == "true"

    def test_no_observability_no_otel_env_vars(self):
        """Test that with_observability=False does NOT inject OTEL env vars."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ComposeConfig(
                output_dir=Path(tmpdir),
                with_observability=False,
            )
            generator = ComposeGenerator()
            compose_file = generator.generate(config)

            content = yaml.safe_load(compose_file.read_text())
            env = content["services"]["ploston"]["environment"]
            assert "PLOSTON_LOGS_ENABLED" not in env
            assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in env
            assert "OTEL_EXPORTER_OTLP_INSECURE" not in env

    def test_generate_custom_port(self):
        """Test generating compose with custom port."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ComposeConfig(
                output_dir=Path(tmpdir),
                port=9000,
            )
            generator = ComposeGenerator()
            compose_file = generator.generate(config)

            content = yaml.safe_load(compose_file.read_text())
            ploston_ports = content["services"]["ploston"]["ports"]
            assert any("9000" in str(p) for p in ploston_ports)

    def test_generate_custom_tag(self):
        """Test generating compose with custom image tag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ComposeConfig(
                output_dir=Path(tmpdir),
                tag="v1.0.0",
            )
            generator = ComposeGenerator()
            compose_file = generator.generate(config)

            content = yaml.safe_load(compose_file.read_text())
            ploston_image = content["services"]["ploston"]["image"]
            assert "v1.0.0" in ploston_image


class TestVolumeManager:
    """Tests for VolumeManager."""

    def test_setup_directories(self):
        """Test creating data directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = VolumeManager(base_dir=Path(tmpdir))
            manager.setup_directories()

            assert (Path(tmpdir) / "data" / "redis").exists()
            assert (Path(tmpdir) / "data" / "ploston").exists()

    def test_generate_seed_config(self):
        """Test generating seed configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = VolumeManager(base_dir=Path(tmpdir))
            manager.setup_directories()
            config_file = manager.generate_seed_config()

            assert config_file is not None
            assert config_file.exists()

            content = yaml.safe_load(config_file.read_text())
            assert "version" in content


class TestAssetManager:
    """Tests for AssetManager."""

    def test_deploy_observability_docker(self):
        """Test deploying Docker observability assets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AssetManager(target_dir=Path(tmpdir))
            obs_compose = manager.deploy_observability_docker()

            assert obs_compose.exists()
            assert obs_compose.name == "docker-compose.observability.yaml"

            # Check that config files were copied
            obs_dir = Path(tmpdir) / "observability"
            assert (obs_dir / "prometheus" / "prometheus.yml").exists()
            assert (obs_dir / "loki" / "loki-config.yaml").exists()
            assert (obs_dir / "tempo" / "tempo-config.yaml").exists()
            assert (obs_dir / "otel" / "config.yaml").exists()
            assert (
                obs_dir / "grafana" / "provisioning" / "datasources" / "datasources.yaml"
            ).exists()
            assert (
                obs_dir / "grafana" / "provisioning" / "dashboards" / "dashboards.yaml"
            ).exists()

    def test_deploy_observability_docker_content(self):
        """Test that deployed compose file has correct services."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AssetManager(target_dir=Path(tmpdir))
            obs_compose = manager.deploy_observability_docker()

            content = yaml.safe_load(obs_compose.read_text())
            assert "prometheus" in content["services"]
            assert "grafana" in content["services"]
            assert "loki" in content["services"]
            assert "tempo" in content["services"]
            assert "otel-collector" in content["services"]

    def test_deploy_observability_docker_no_overwrite(self):
        """Test that existing files are not overwritten by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AssetManager(target_dir=Path(tmpdir))

            # First deploy
            manager.deploy_observability_docker()

            # Modify a file
            prom_config = Path(tmpdir) / "observability" / "prometheus" / "prometheus.yml"
            prom_config.write_text("modified")

            # Second deploy without overwrite
            manager.deploy_observability_docker(overwrite=False)
            assert prom_config.read_text() == "modified"

    def test_deploy_observability_docker_overwrite(self):
        """Test that overwrite=True replaces existing files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AssetManager(target_dir=Path(tmpdir))

            # First deploy
            manager.deploy_observability_docker()

            # Modify a file
            prom_config = Path(tmpdir) / "observability" / "prometheus" / "prometheus.yml"
            prom_config.write_text("modified")

            # Second deploy with overwrite
            manager.deploy_observability_docker(overwrite=True)
            assert prom_config.read_text() != "modified"

    def test_deploy_observability_k8s(self):
        """Test deploying K8s observability manifests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AssetManager(target_dir=Path(tmpdir))
            k8s_dir = manager.deploy_observability_k8s()

            assert k8s_dir.exists()
            assert (k8s_dir / "prometheus.yaml").exists()
            assert (k8s_dir / "grafana.yaml").exists()
            assert (k8s_dir / "loki.yaml").exists()
            assert (k8s_dir / "tempo.yaml").exists()
            assert (k8s_dir / "kustomization.yaml").exists()

    def test_get_observability_compose_path(self):
        """Test getting expected observability compose path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AssetManager(target_dir=Path(tmpdir))
            path = manager.get_observability_compose_path()
            assert str(path).endswith("observability/docker-compose.observability.yaml")

    def test_grafana_dashboards_deployed(self):
        """Test that Grafana dashboards are deployed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AssetManager(target_dir=Path(tmpdir))
            manager.deploy_observability_docker()

            dashboards_dir = Path(tmpdir) / "observability" / "grafana" / "dashboards"
            assert dashboards_dir.exists()
            json_files = list(dashboards_dir.glob("*.json"))
            assert len(json_files) >= 1, "Expected at least one dashboard JSON file"
