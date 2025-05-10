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

            # Check ploston volumes include workflows and schemas bind-mounts
            ploston_volumes = content["services"]["ploston"]["volumes"]
            assert "./data/workflows:/app/workflows" in ploston_volumes
            assert "./data/ploston:/app/data" in ploston_volumes
            assert "./data/schemas:/home/ploston/.ploston/schemas" in ploston_volumes

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

    def test_observability_injects_clickhouse_env_vars(self):
        """S-303 T-976: with_observability=True wires ClickHouse selection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ComposeConfig(
                output_dir=Path(tmpdir),
                with_observability=True,
            )
            generator = ComposeGenerator()
            compose_file = generator.generate(config)

            content = yaml.safe_load(compose_file.read_text())
            env = content["services"]["ploston"]["environment"]
            assert env["PLOSTON_TELEMETRY_BACKEND"] == "clickhouse"
            assert env["PLOSTON_CLICKHOUSE_HOST"] == "clickhouse"
            assert env["PLOSTON_CLICKHOUSE_PORT"] == "8123"
            assert env["PLOSTON_CLICKHOUSE_DATABASE"] == "ploston"
            assert env["PLOSTON_CLICKHOUSE_USERNAME"] == "default"
            assert env["PLOSTON_CLICKHOUSE_PASSWORD"] == ""
            assert env["PLOSTON_CLICKHOUSE_SECURE"] == "false"

    def test_no_observability_no_clickhouse_env_vars(self):
        """Without observability, the ClickHouse vars must be absent so the
        CP keeps its sqlite default (DEC-193 fail-safe)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ComposeConfig(
                output_dir=Path(tmpdir),
                with_observability=False,
            )
            generator = ComposeGenerator()
            compose_file = generator.generate(config)

            content = yaml.safe_load(compose_file.read_text())
            env = content["services"]["ploston"]["environment"]
            for key in (
                "PLOSTON_TELEMETRY_BACKEND",
                "PLOSTON_CLICKHOUSE_HOST",
                "PLOSTON_CLICKHOUSE_PORT",
                "PLOSTON_CLICKHOUSE_DATABASE",
                "PLOSTON_CLICKHOUSE_USERNAME",
                "PLOSTON_CLICKHOUSE_PASSWORD",
                "PLOSTON_CLICKHOUSE_SECURE",
            ):
                assert key not in env

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
            assert (Path(tmpdir) / "data" / "workflows").exists()
            assert (Path(tmpdir) / "data" / "schemas").exists()

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

    def test_seed_workflows_into_empty_dir(self):
        """Seed copies bundled workflows when the dir contains no YAML files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = VolumeManager(base_dir=Path(tmpdir))
            manager.setup_directories()

            seeded = manager.seed_workflows()

            workflows_dir = Path(tmpdir) / "data" / "workflows"
            hello = workflows_dir / "hello_world.yaml"
            assert hello.exists(), "hello_world.yaml should be seeded"
            assert hello in seeded
            content = yaml.safe_load(hello.read_text())
            assert content["name"] == "hello_world"
            assert "greet" in content["steps"][0]["id"]

    def test_seed_workflows_skips_when_yaml_present(self):
        """Seed must never overwrite or even add to an already-populated dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = VolumeManager(base_dir=Path(tmpdir))
            manager.setup_directories()

            workflows_dir = Path(tmpdir) / "data" / "workflows"
            user_wf = workflows_dir / "my_workflow.yaml"
            user_wf.write_text("name: my_workflow\nsteps: []\n")

            seeded = manager.seed_workflows()

            assert seeded == []
            assert not (workflows_dir / "hello_world.yaml").exists()
            # User content untouched
            assert user_wf.read_text().startswith("name: my_workflow")

    def test_seed_workflows_creates_dir_when_missing(self):
        """Calling seed before setup_directories still works (creates the dir)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = VolumeManager(base_dir=Path(tmpdir))

            seeded = manager.seed_workflows()

            workflows_dir = Path(tmpdir) / "data" / "workflows"
            assert workflows_dir.exists()
            assert (workflows_dir / "hello_world.yaml").exists()
            assert len(seeded) >= 1


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
            assert (obs_dir / "clickhouse" / "init" / "01-create-database.sql").exists()
            # users.d override drops the image-bundled localhost-only network
            # restriction; without this CP cannot connect to ClickHouse.
            users_xml = obs_dir / "clickhouse" / "users.d" / "default-user.xml"
            assert users_xml.exists()
            assert "<ip>::/0</ip>" in users_xml.read_text()
            assert not (obs_dir / "loki").exists()
            assert not (obs_dir / "tempo").exists()
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
            assert "clickhouse" in content["services"]
            assert "loki" not in content["services"]
            assert "tempo" not in content["services"]
            assert "otel-collector" in content["services"]
            ch_volumes = content["services"]["clickhouse"]["volumes"]
            assert any("/etc/clickhouse-server/users.d" in v for v in ch_volumes), (
                f"users.d mount missing from clickhouse volumes: {ch_volumes!r}"
            )

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
            assert (k8s_dir / "clickhouse.yaml").exists()
            assert not (k8s_dir / "loki.yaml").exists()
            assert not (k8s_dir / "tempo.yaml").exists()
            assert (k8s_dir / "kustomization.yaml").exists()

    def test_clickhouse_k8s_mounts_users_d_override(self):
        """The K8s manifest must ship a ``clickhouse-users`` ConfigMap and
        mount it at /etc/clickhouse-server/users.d so the network restriction
        on the bundled ``default-user.xml`` is shadowed (mirrors the docker
        compose users.d mount)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AssetManager(target_dir=Path(tmpdir))
            k8s_dir = manager.deploy_observability_k8s()
            docs = list(yaml.safe_load_all((k8s_dir / "clickhouse.yaml").read_text()))
            kinds = {(d.get("kind"), d.get("metadata", {}).get("name")) for d in docs if d}
            assert ("ConfigMap", "clickhouse-users") in kinds
            users_cm = next(
                d for d in docs if d and d.get("metadata", {}).get("name") == "clickhouse-users"
            )
            assert "<ip>::/0</ip>" in users_cm["data"]["default-user.xml"]
            deployment = next(d for d in docs if d and d.get("kind") == "Deployment")
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            mount_paths = [m["mountPath"] for m in container["volumeMounts"]]
            assert "/etc/clickhouse-server/users.d" in mount_paths

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
