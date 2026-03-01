"""Unit tests for bootstrap compose module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from ploston_cli.bootstrap import ComposeConfig, ComposeGenerator, VolumeManager


class TestComposeConfig:
    """Tests for ComposeConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ComposeConfig()
        assert config.tag == "latest"
        assert config.port == 8082
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

    def test_generate_with_observability(self):
        """Test generating compose with observability stack."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ComposeConfig(
                output_dir=Path(tmpdir),
                with_observability=True,
            )
            generator = ComposeGenerator()
            compose_file = generator.generate(config)

            content = yaml.safe_load(compose_file.read_text())

            # Check observability services
            assert "prometheus" in content["services"]
            assert "grafana" in content["services"]
            assert "loki" in content["services"]

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

    def test_setup_observability_directories(self):
        """Test creating observability directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = VolumeManager(base_dir=Path(tmpdir))
            manager.setup_observability_directories()

            assert (Path(tmpdir) / "data" / "prometheus").exists()
            assert (Path(tmpdir) / "data" / "grafana").exists()
            assert (Path(tmpdir) / "data" / "loki").exists()

    def test_generate_prometheus_config(self):
        """Test generating Prometheus configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = VolumeManager(base_dir=Path(tmpdir))
            manager.setup_observability_directories()
            config_file = manager.generate_prometheus_config()

            assert config_file is not None
            assert config_file.exists()

    def test_generate_loki_config(self):
        """Test generating Loki configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = VolumeManager(base_dir=Path(tmpdir))
            manager.setup_observability_directories()
            config_file = manager.generate_loki_config()

            assert config_file is not None
            assert config_file.exists()
