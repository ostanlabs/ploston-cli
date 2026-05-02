"""Session Inspector dashboard tests (S-299 / T-962)."""

import json
import os

import pytest

_PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
_DOCKER_PATH = os.path.join(
    _PKG_ROOT,
    "src/ploston_cli/bootstrap/assets/docker/observability/grafana/dashboards/session-inspector.json",
)


@pytest.fixture
def dashboard() -> dict:
    with open(_DOCKER_PATH) as f:
        return json.load(f)


def test_session_inspector_dashboard_exists() -> None:
    assert os.path.exists(_DOCKER_PATH)


def test_session_inspector_uid_is_canonical(dashboard: dict) -> None:
    assert dashboard["uid"] == "ploston-session-inspector"


def test_session_inspector_has_required_panels(dashboard: dict) -> None:
    titles = [p.get("title", "") for p in dashboard.get("panels", [])]
    # Spec calls for the following panels (Recent Sessions = entry,
    # then 5 stats, then workflow, timeline, inspector, distribution, events).
    assert "Recent Sessions" in titles
    assert "Tool Calls" in titles
    assert "Errors" in titles
    assert "Workflow Executions" in titles
    assert "Tool Call Timeline" in titles
    assert "Inspect One Tool Call" in titles
    assert "Tool Usage Distribution" in titles
    assert "Free-form Events" in titles


def test_session_inspector_has_session_id_variable(dashboard: dict) -> None:
    var_names = {v["name"] for v in dashboard.get("templating", {}).get("list", [])}
    assert "session_id" in var_names
    assert "execution_id" in var_names
    assert "tool_name" in var_names
    assert "call_id" in var_names


def test_call_id_variable_is_hidden(dashboard: dict) -> None:
    """`call_id` is set only via Panel 3 data-link click — must be hidden."""
    call_id_var = next(v for v in dashboard["templating"]["list"] if v["name"] == "call_id")
    assert call_id_var.get("hide") == 2


def test_tool_name_variable_is_multi_select(dashboard: dict) -> None:
    """Spec requires tool_name multi-select with CSV format for splitByChar."""
    tool_name_var = next(v for v in dashboard["templating"]["list"] if v["name"] == "tool_name")
    assert tool_name_var.get("multi") is True
    assert tool_name_var.get("allValue") == ""


def test_session_inspector_uses_clickhouse_datasource(dashboard: dict) -> None:
    """Every panel target with rawSql must point at uid='clickhouse'."""
    for panel in dashboard.get("panels", []):
        for target in panel.get("targets", []):
            if "rawSql" not in target:
                continue
            ds = target.get("datasource") or panel.get("datasource")
            assert (isinstance(ds, dict) and ds.get("uid") == "clickhouse") or ds == "clickhouse"


def test_recent_sessions_panel_has_data_link_to_session_id(dashboard: dict) -> None:
    """Panel 0 must have a data link wiring session_id → var-session_id."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Recent Sessions")
    overrides = panel.get("fieldConfig", {}).get("overrides", [])
    found = False
    for override in overrides:
        if override.get("matcher", {}).get("options") == "session_id":
            for prop in override.get("properties", []):
                if prop.get("id") == "links":
                    for link in prop.get("value", []):
                        if "var-session_id" in link.get("url", ""):
                            found = True
    assert found, "Recent Sessions panel missing var-session_id data link"


def test_tool_call_timeline_has_call_id_drill_link(dashboard: dict) -> None:
    """Panel 3 must have a data link wiring call_id → var-call_id (T-961)."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Tool Call Timeline")
    overrides = panel.get("fieldConfig", {}).get("overrides", [])
    found = False
    for override in overrides:
        if override.get("matcher", {}).get("options") == "call_id":
            for prop in override.get("properties", []):
                if prop.get("id") == "links":
                    for link in prop.get("value", []):
                        if "var-call_id" in link.get("url", ""):
                            found = True
    assert found, "Tool Call Timeline panel missing var-call_id data link"


def test_centerpiece_query_uses_splitbychar_for_tool_filter(dashboard: dict) -> None:
    """Panel 3 must consume tool_name multi-select via splitByChar."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Tool Call Timeline")
    sql = panel["targets"][0]["rawSql"]
    assert "splitByChar(',', '$tool_name')" in sql


def test_inspect_one_panel_filters_by_call_id(dashboard: dict) -> None:
    """Panel 4 must filter on call_id and use defensive LIMIT 1."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Inspect One Tool Call")
    sql = panel["targets"][0]["rawSql"]
    assert "call_id = '$call_id'" in sql
    assert "LIMIT 1" in sql


def test_events_panel_targets_ploston_events_view(dashboard: dict) -> None:
    """Panel 6 must query ploston.events (the SQL view over otel_logs)."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Free-form Events")
    sql = panel["targets"][0]["rawSql"]
    assert "ploston.events" in sql
    assert "session_id = '$session_id'" in sql
