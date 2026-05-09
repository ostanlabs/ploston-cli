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
    "session-inspector.json",
    "call-inspector.json",
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


@pytest.mark.parametrize("filename", ["execution-logs.json"])
def test_migrated_log_dashboards_have_clickhouse_panels(filename: str) -> None:
    """Dashboards migrated from Loki to ClickHouse must have at least one rawSql panel."""
    dashboard = _load(os.path.join(_DOCKER_DIR, filename))
    found = False
    for panel in _iter_panels(dashboard):
        for target in panel.get("targets", []) or []:
            if "rawSql" in target:
                found = True
                break
    assert found, f"{filename} has no rawSql panel after migration"


@pytest.mark.parametrize("filename", DASHBOARDS)
def test_clickhouse_rawsql_targets_set_format(filename: str) -> None:
    """Every ClickHouse rawSql target must set ``format`` to match its panel.

    Without an explicit format, ``grafana-clickhouse-datasource`` auto-pivots
    the result into a ``timeseries-wide`` frame: string columns get crammed
    into the field labels and panels render as a single mangled row.
    Reproducible via ``POST /api/ds/query`` against a live Grafana with vs
    without the field. The plugin enum is
    ``0=Auto, 1=Table, 2=Logs, 3=Time series, 4=Trace``.

    Mapping per panel type:
      - ``logs`` panel  -> ``format=2``
      - everything else (``table``, ``stat``, ``piechart``, ``timeseries``)
        is rendered from a table frame -> ``format=1``.
    """
    dashboard = _load(os.path.join(_DOCKER_DIR, filename))
    bad: list[str] = []
    for panel in _iter_panels(dashboard):
        panel_ds_uid = _datasource_uid(panel.get("datasource"))
        expected_format = 2 if panel.get("type") == "logs" else 1
        for target in panel.get("targets", []) or []:
            if "rawSql" not in target:
                continue
            target_ds_uid = _datasource_uid(target.get("datasource"))
            if (target_ds_uid or panel_ds_uid) != "clickhouse":
                continue
            if target.get("format") != expected_format:
                bad.append(
                    f"panel '{panel.get('title')}' (type={panel.get('type')}) "
                    f"refId={target.get('refId')!r} "
                    f"format={target.get('format')!r}, expected {expected_format}"
                )
    assert not bad, f"{filename} ClickHouse targets have wrong format: {bad}"


def test_execution_logs_has_session_id_variable() -> None:
    """Execution-logs dashboard must expose a session_id textbox variable
    so users (and drill-down links from Session Inspector) can scope the
    workflow executions list to a single agent conversation."""
    dashboard = _load(os.path.join(_DOCKER_DIR, "execution-logs.json"))
    var_names = {v["name"] for v in dashboard.get("templating", {}).get("list", [])}
    assert "session_id" in var_names, (
        f"execution-logs.json missing session_id template variable, got {var_names!r}"
    )


def test_execution_logs_recent_executions_filters_by_session_id() -> None:
    """The Recent Workflow Executions table must include the optional
    session_id filter so it respects the variable when set."""
    dashboard = _load(os.path.join(_DOCKER_DIR, "execution-logs.json"))
    # Panel [1] is the unnamed table under the "Recent Workflow Executions" row
    table_panel = None
    for panel in dashboard.get("panels", []):
        if panel.get("type") == "table" and "executions" in (
            panel.get("targets", [{}])[0].get("rawSql", "")
        ):
            table_panel = panel
            break
    assert table_panel is not None, "Could not find the executions table panel"
    sql = table_panel["targets"][0]["rawSql"]
    assert "session_id" in sql, "Recent Workflow Executions SQL must filter by session_id"
    assert "'$session_id' = ''" in sql, (
        "session_id filter must be optional (bypass when variable is empty)"
    )
