"""Tests for bootstrap bundled assets.

These tests validate the observability configuration files bundled as CLI assets.
They check:
- Prometheus configuration structure
- OTEL Collector configuration structure
- Loki configuration structure
- Tempo configuration structure
- Grafana datasource provisioning
- Grafana dashboard JSON files
"""

import json
from pathlib import Path

import pytest
import yaml

# Assets directory within the CLI package
ASSETS_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "ploston_cli"
    / "bootstrap"
    / "assets"
    / "docker"
    / "observability"
)


class TestPrometheusConfig:
    """Tests for Prometheus configuration."""

    @pytest.fixture
    def prometheus_config(self) -> dict:
        config_path = ASSETS_DIR / "prometheus" / "prometheus.yml"
        with open(config_path) as f:
            return yaml.safe_load(f)

    def test_prometheus_config_exists(self):
        assert (ASSETS_DIR / "prometheus" / "prometheus.yml").exists()

    def test_has_global_config(self, prometheus_config: dict):
        assert "global" in prometheus_config
        assert "scrape_interval" in prometheus_config["global"]

    def test_has_ploston_scrape_job(self, prometheus_config: dict):
        scrape_configs = prometheus_config.get("scrape_configs", [])
        job_names = [job.get("job_name") for job in scrape_configs]
        assert "ploston" in job_names or "ael" in job_names


class TestOtelCollectorConfig:
    """Tests for OTEL Collector configuration."""

    @pytest.fixture
    def otel_config(self) -> dict:
        config_path = ASSETS_DIR / "otel" / "config.yaml"
        with open(config_path) as f:
            return yaml.safe_load(f)

    def test_otel_config_exists(self):
        assert (ASSETS_DIR / "otel" / "config.yaml").exists()

    def test_has_otlp_receiver(self, otel_config: dict):
        assert "receivers" in otel_config
        assert "otlp" in otel_config["receivers"]

    def test_has_prometheus_exporter(self, otel_config: dict):
        assert "exporters" in otel_config
        assert "prometheus" in otel_config["exporters"]

    def test_has_loki_exporter(self, otel_config: dict):
        assert "loki" in otel_config["exporters"]

    def test_has_tempo_exporter(self, otel_config: dict):
        assert "otlp/tempo" in otel_config["exporters"]

    def test_has_metrics_pipeline(self, otel_config: dict):
        assert "service" in otel_config
        assert "pipelines" in otel_config["service"]
        assert "metrics" in otel_config["service"]["pipelines"]

    def test_has_logs_pipeline(self, otel_config: dict):
        assert "logs" in otel_config["service"]["pipelines"]

    def test_has_traces_pipeline(self, otel_config: dict):
        assert "traces" in otel_config["service"]["pipelines"]


class TestLokiConfig:
    """Tests for Loki configuration."""

    @pytest.fixture
    def loki_config(self) -> dict:
        config_path = ASSETS_DIR / "loki" / "loki-config.yaml"
        with open(config_path) as f:
            return yaml.safe_load(f)

    def test_loki_config_exists(self):
        assert (ASSETS_DIR / "loki" / "loki-config.yaml").exists()

    def test_has_server_config(self, loki_config: dict):
        assert "server" in loki_config
        assert "http_listen_port" in loki_config["server"]

    def test_has_schema_config(self, loki_config: dict):
        assert "schema_config" in loki_config


class TestTempoConfig:
    """Tests for Tempo configuration."""

    @pytest.fixture
    def tempo_config(self) -> dict:
        config_path = ASSETS_DIR / "tempo" / "tempo-config.yaml"
        with open(config_path) as f:
            return yaml.safe_load(f)

    def test_tempo_config_exists(self):
        assert (ASSETS_DIR / "tempo" / "tempo-config.yaml").exists()

    def test_has_server_config(self, tempo_config: dict):
        assert "server" in tempo_config

    def test_has_distributor_config(self, tempo_config: dict):
        assert "distributor" in tempo_config

    def test_has_storage_config(self, tempo_config: dict):
        assert "storage" in tempo_config


class TestGrafanaDatasources:
    """Tests for Grafana datasource provisioning."""

    @pytest.fixture
    def datasources_config(self) -> dict:
        config_path = ASSETS_DIR / "grafana" / "provisioning" / "datasources" / "datasources.yaml"
        with open(config_path) as f:
            return yaml.safe_load(f)

    def test_datasources_config_exists(self):
        config_path = ASSETS_DIR / "grafana" / "provisioning" / "datasources" / "datasources.yaml"
        assert config_path.exists()

    def test_has_prometheus_datasource(self, datasources_config: dict):
        datasources = datasources_config.get("datasources", [])
        names = [ds.get("name") for ds in datasources]
        assert "Prometheus" in names

    def test_has_loki_datasource(self, datasources_config: dict):
        datasources = datasources_config.get("datasources", [])
        names = [ds.get("name") for ds in datasources]
        assert "Loki" in names

    def test_has_tempo_datasource(self, datasources_config: dict):
        datasources = datasources_config.get("datasources", [])
        names = [ds.get("name") for ds in datasources]
        assert "Tempo" in names


class TestGrafanaDashboards:
    """Tests for Grafana dashboard JSON files."""

    DASHBOARDS_DIR = ASSETS_DIR / "grafana" / "dashboards"

    def test_overview_dashboard_exists(self):
        assert (self.DASHBOARDS_DIR / "ploston-overview.json").exists()

    def test_tool_usage_dashboard_exists(self):
        assert (self.DASHBOARDS_DIR / "tool-usage.json").exists()

    def test_chain_detection_dashboard_exists(self):
        assert (self.DASHBOARDS_DIR / "chain-detection.json").exists()

    def test_token_savings_dashboard_exists(self):
        assert (self.DASHBOARDS_DIR / "token-savings.json").exists()

    def test_overview_dashboard_valid_json(self):
        with open(self.DASHBOARDS_DIR / "ploston-overview.json") as f:
            dashboard = json.load(f)
        assert "panels" in dashboard
        assert "title" in dashboard
        assert dashboard["title"] == "Ploston Overview"

    def test_tool_usage_dashboard_valid_json(self):
        with open(self.DASHBOARDS_DIR / "tool-usage.json") as f:
            dashboard = json.load(f)
        assert "panels" in dashboard
        assert dashboard["title"] == "Ploston Tool Usage"

    def test_chain_detection_dashboard_valid_json(self):
        with open(self.DASHBOARDS_DIR / "chain-detection.json") as f:
            dashboard = json.load(f)
        assert "panels" in dashboard
        assert dashboard["title"] == "Ploston Chain Detection"

    def test_token_savings_dashboard_valid_json(self):
        with open(self.DASHBOARDS_DIR / "token-savings.json") as f:
            dashboard = json.load(f)
        assert "panels" in dashboard
        assert dashboard["title"] == "Ploston Token Savings"

    def test_overview_dashboard_has_required_panels(self):
        with open(self.DASHBOARDS_DIR / "ploston-overview.json") as f:
            dashboard = json.load(f)
        panel_titles = [p.get("title") for p in dashboard.get("panels", [])]
        assert "Total Workflow Executions" in panel_titles
        assert "Workflow Success Rate" in panel_titles
        assert "Connected Runners" in panel_titles


class TestObservabilityComposeFile:
    """Tests for the observability Docker Compose overlay file."""

    @pytest.fixture
    def compose_config(self) -> dict:
        compose_path = ASSETS_DIR / "docker-compose.observability.yaml"
        with open(compose_path) as f:
            return yaml.safe_load(f)

    def test_compose_file_exists(self):
        assert (ASSETS_DIR / "docker-compose.observability.yaml").exists()

    def test_has_prometheus_service(self, compose_config: dict):
        assert "prometheus" in compose_config.get("services", {})

    def test_has_grafana_service(self, compose_config: dict):
        assert "grafana" in compose_config.get("services", {})

    def test_has_loki_service(self, compose_config: dict):
        assert "loki" in compose_config.get("services", {})

    def test_has_tempo_service(self, compose_config: dict):
        assert "tempo" in compose_config.get("services", {})

    def test_has_otel_collector_service(self, compose_config: dict):
        assert "otel-collector" in compose_config.get("services", {})
