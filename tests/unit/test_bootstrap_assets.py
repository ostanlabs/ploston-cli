"""Tests for bootstrap bundled assets.

These tests validate the observability configuration files bundled as CLI assets.
They check:
- Prometheus configuration structure
- OTEL Collector configuration structure (post-S-297: ClickHouse exporter)
- ClickHouse init scripts (post-S-297, replaces Loki + Tempo per DEC-191)
- Grafana datasource provisioning (Prometheus + ClickHouse)
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

    def test_has_clickhouse_exporter(self, otel_config: dict):
        assert "clickhouse" in otel_config["exporters"]
        ch = otel_config["exporters"]["clickhouse"]
        assert ch["endpoint"].startswith("tcp://clickhouse")
        assert ch["database"] == "ploston"
        # Spec: do NOT override exporter table names.
        assert "logs_table_name" not in ch
        assert "traces_table_name" not in ch

    def test_no_loki_or_tempo_exporters(self, otel_config: dict):
        """DEC-191: Loki and Tempo exporters fully removed."""
        assert "loki" not in otel_config["exporters"]
        assert "otlp/tempo" not in otel_config["exporters"]

    def test_no_loki_hints_processors(self, otel_config: dict):
        """DEC-154's loki_hints processors are the high-cardinality mistake;
        DEC-191 removes both."""
        processors = otel_config.get("processors", {})
        assert "attributes/loki_hints" not in processors
        assert "resource/loki_hints" not in processors

    def test_keeps_memory_limiter_resource_batch(self, otel_config: dict):
        for proc in ("memory_limiter", "resource", "batch"):
            assert proc in otel_config["processors"], f"missing processor: {proc}"

    def test_logs_pipeline_routes_to_clickhouse(self, otel_config: dict):
        logs = otel_config["service"]["pipelines"]["logs"]
        assert "clickhouse" in logs["exporters"]
        assert "loki" not in logs["exporters"]

    def test_traces_pipeline_routes_to_clickhouse(self, otel_config: dict):
        traces = otel_config["service"]["pipelines"]["traces"]
        assert "clickhouse" in traces["exporters"]
        assert "otlp/tempo" not in traces["exporters"]

    def test_has_metrics_pipeline(self, otel_config: dict):
        assert "service" in otel_config
        assert "pipelines" in otel_config["service"]
        assert "metrics" in otel_config["service"]["pipelines"]

    def test_has_logs_pipeline(self, otel_config: dict):
        assert "logs" in otel_config["service"]["pipelines"]

    def test_has_traces_pipeline(self, otel_config: dict):
        assert "traces" in otel_config["service"]["pipelines"]


class TestClickHouseInitScripts:
    """Tests for ClickHouse init SQL scripts (S-297)."""

    INIT_DIR = ASSETS_DIR / "clickhouse" / "init"

    def test_init_dir_exists(self):
        assert self.INIT_DIR.is_dir()

    def test_create_database_script_exists(self):
        script = self.INIT_DIR / "01-create-database.sql"
        assert script.exists()
        content = script.read_text()
        assert "CREATE DATABASE IF NOT EXISTS ploston" in content

    def test_no_loki_or_tempo_assets(self):
        """DEC-191: loki/ and tempo/ asset directories are gone."""
        assert not (ASSETS_DIR / "loki").exists()
        assert not (ASSETS_DIR / "tempo").exists()


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

    def test_has_clickhouse_datasource(self, datasources_config: dict):
        """DEC-191: Loki + Tempo replaced by ClickHouse datasource."""
        datasources = datasources_config.get("datasources", [])
        names = [ds.get("name") for ds in datasources]
        assert "ClickHouse" in names
        ch = next(ds for ds in datasources if ds["name"] == "ClickHouse")
        assert ch["type"] == "grafana-clickhouse-datasource"
        assert ch["uid"] == "clickhouse"
        assert ch["jsonData"]["server"] == "clickhouse"
        assert ch["jsonData"]["defaultDatabase"] == "ploston"

    def test_no_loki_or_tempo_datasource(self, datasources_config: dict):
        names = [ds.get("name") for ds in datasources_config.get("datasources", [])]
        assert "Loki" not in names
        assert "Tempo" not in names


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

    def test_workflow_execution_logs_dashboard_exists(self):
        assert (self.DASHBOARDS_DIR / "execution-logs.json").exists()

    def test_workflow_execution_logs_dashboard_valid_json(self):
        with open(self.DASHBOARDS_DIR / "execution-logs.json") as f:
            dashboard = json.load(f)
        assert "panels" in dashboard
        assert dashboard["title"] == "Workflow Execution Logs"
        assert dashboard["uid"] == "ploston-workflow-execution-logs"

    def test_workflow_execution_logs_queries_target_executions_table(self):
        """Post-S-298: every rawSql panel must hit ploston.executions/steps/tool_calls."""
        with open(self.DASHBOARDS_DIR / "execution-logs.json") as f:
            dashboard = json.load(f)
        targets_with_sql = []
        for panel in dashboard.get("panels", []):
            for target in panel.get("targets", []):
                if "rawSql" in target:
                    targets_with_sql.append(target["rawSql"])
        assert targets_with_sql, "execution-logs.json has no rawSql panels"
        for sql in targets_with_sql:
            assert "ploston." in sql
            assert "loki" not in sql.lower()

    # NOTE: Direct Tool Logs dashboard was removed — its use cases (browse
    # recent calls, drill into one) are now served by the Session Inspector +
    # Call Inspector pair, which provide better hierarchy and per-call detail.

    # NOTE: test_otel_config_promotes_source_label removed per S-297/T-951.
    # DEC-154's loki_hints processors (and the ael_ prefixed Loki label
    # promotion they configured) were eliminated by DEC-191. ael_source and
    # related context fields are now ClickHouse columns, not stream labels.


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

    def test_has_clickhouse_service(self, compose_config: dict):
        """DEC-191: replaces Loki + Tempo."""
        services = compose_config.get("services", {})
        assert "clickhouse" in services
        ch = services["clickhouse"]
        assert ch["image"].startswith("clickhouse/clickhouse-server")
        # Healthcheck uses clickhouse-client (portable across alpine/debian).
        hc_test = ch["healthcheck"]["test"]
        assert "clickhouse-client" in hc_test

    def test_no_loki_or_tempo_service(self, compose_config: dict):
        services = compose_config.get("services", {})
        assert "loki" not in services
        assert "tempo" not in services

    def test_has_otel_collector_service(self, compose_config: dict):
        assert "otel-collector" in compose_config.get("services", {})

    def test_otel_collector_image_version(self, compose_config: dict):
        """S-297: bumped to contrib 0.105.0."""
        otel = compose_config["services"]["otel-collector"]
        assert otel["image"] == "otel/opentelemetry-collector-contrib:0.105.0"

    def test_otel_collector_ports_restored(self, compose_config: dict):
        """4317/4318 restored once Tempo no longer claims those ports."""
        otel = compose_config["services"]["otel-collector"]
        port_mappings = otel.get("ports", [])
        assert "4317:4317" in port_mappings
        assert "4318:4318" in port_mappings
