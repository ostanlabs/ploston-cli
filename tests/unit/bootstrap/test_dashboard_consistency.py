"""Generalized dashboard consistency tests (S-298 / T-958).

Replaces the per-dashboard byte-identity test with a parametrized loop over
every dashboard the CLI ships. Also asserts that no dashboard references
Loki or Tempo datasources after DEC-191 / M-082, and that any panel which
emits raw SQL targets the ClickHouse datasource (`uid: clickhouse`).
"""

import json
import os

import pytest

_PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
_DOCKER_DIR = os.path.join(
    _PKG_ROOT,
    "src/ploston_cli/bootstrap/assets/docker/observability/grafana/dashboards",
)
_MONOREPO_ROOT = os.path.abspath(os.path.join(_PKG_ROOT, "../.."))
_HELM_DIR = os.path.join(_MONOREPO_ROOT, "charts/ploston-observability/dashboards")

DASHBOARDS = [
    "ploston-overview.json",
    "tool-usage.json",
    "chain-detection.json",
    "token-savings.json",
    "execution-logs.json",
    "direct-tool-logs.json",
    "session-inspector.json",
]


def _load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _iter_panels(dashboard: dict):
    """Yield panels, recursing into row-nested panels."""
    for panel in dashboard.get("panels", []) or []:
        yield panel
        for nested in panel.get("panels", []) or []:
            yield nested


def _datasource_uid(ref) -> str | None:
    if isinstance(ref, dict):
        return ref.get("uid")
    if isinstance(ref, str):
        return ref
    return None


@pytest.mark.parametrize("filename", DASHBOARDS)
def test_dashboard_exists_in_docker_assets(filename: str) -> None:
    assert os.path.exists(os.path.join(_DOCKER_DIR, filename))


@pytest.mark.parametrize("filename", DASHBOARDS)
@pytest.mark.skipif(not os.path.isdir(_HELM_DIR), reason="Helm chart dir absent")
def test_dashboard_copies_byte_identical(filename: str) -> None:
    """Docker bootstrap copy and Helm chart copy must match byte-for-byte.

    Skipped when the Helm chart directory is not part of the checkout
    (e.g. standalone ploston-cli installs).
    """
    docker_path = os.path.join(_DOCKER_DIR, filename)
    helm_path = os.path.join(_HELM_DIR, filename)
    assert os.path.exists(helm_path), f"Missing helm copy of {filename}"
    with open(docker_path, "rb") as f:
        docker_bytes = f.read()
    with open(helm_path, "rb") as f:
        helm_bytes = f.read()
    assert docker_bytes == helm_bytes, f"{filename} differs between docker and helm copies"


@pytest.mark.parametrize("filename", DASHBOARDS)
def test_no_loki_or_tempo_references(filename: str) -> None:
    """DEC-191: every dashboard must be free of Loki / Tempo refs."""
    text = open(os.path.join(_DOCKER_DIR, filename)).read()
    for needle in (
        '"type": "loki"',
        '"type":"loki"',
        '"type": "tempo"',
        '"type":"tempo"',
        '"uid": "loki"',
        '"uid":"loki"',
        '"uid": "tempo"',
        '"uid":"tempo"',
    ):
        assert needle not in text, f"{filename} still references {needle}"


@pytest.mark.parametrize("filename", DASHBOARDS)
def test_rawsql_panels_use_clickhouse_datasource(filename: str) -> None:
    """Any panel target with `rawSql` must point at uid='clickhouse'."""
    dashboard = _load(os.path.join(_DOCKER_DIR, filename))
    for panel in _iter_panels(dashboard):
        panel_ds_uid = _datasource_uid(panel.get("datasource"))
        for target in panel.get("targets", []) or []:
            if "rawSql" not in target:
                continue
            target_ds_uid = _datasource_uid(target.get("datasource"))
            uid = target_ds_uid or panel_ds_uid
            assert uid == "clickhouse", (
                f"{filename} panel '{panel.get('title')}' uses rawSql but "
                f"datasource uid is {uid!r} (expected 'clickhouse')"
            )


def test_execution_logs_filename_canonical() -> None:
    """The dashboard file is `execution-logs.json`, not the legacy
    `workflow-execution-logs.json` (S-298 spec correction)."""
    assert os.path.exists(os.path.join(_DOCKER_DIR, "execution-logs.json"))
    assert not os.path.exists(os.path.join(_DOCKER_DIR, "workflow-execution-logs.json"))


@pytest.mark.parametrize("filename", ["execution-logs.json", "direct-tool-logs.json"])
def test_migrated_log_dashboards_have_clickhouse_panels(filename: str) -> None:
    """The two migrated dashboards must have at least one rawSql panel."""
    dashboard = _load(os.path.join(_DOCKER_DIR, filename))
    found = False
    for panel in _iter_panels(dashboard):
        for target in panel.get("targets", []) or []:
            if "rawSql" in target:
                found = True
                break
    assert found, f"{filename} has no rawSql panel after migration"
