"""Session Inspector dashboard tests (S-299 / T-962)."""

import json
import os

import pytest

_PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
_DOCKER_PATH = os.path.join(
    _PKG_ROOT,
    "src/ploston_cli/bootstrap/assets/docker/observability/grafana/dashboards/session-inspector.json",
)
_CALL_INSPECTOR_PATH = os.path.join(
    _PKG_ROOT,
    "src/ploston_cli/bootstrap/assets/docker/observability/grafana/dashboards/call-inspector.json",
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
    # Recent Sessions = entry, then stats, workflow, timeline, distribution,
    # events. The "Inspect One Tool Call" panel was extracted to a dedicated
    # `ploston-call-inspector` dashboard reached via a Tool Call Timeline
    # drill-down link, so it is no longer expected here.
    assert "Recent Sessions" in titles
    assert "Tool Calls" in titles
    assert "Errors" in titles
    assert "Workflow Executions" in titles
    assert "Tool Call Timeline" in titles
    assert "Tool Usage Distribution" in titles
    assert "Free-form Events" in titles


def test_session_inspector_has_only_session_id_variable(dashboard: dict) -> None:
    """Only `session_id` is exposed as a template variable on this dashboard.

    `execution_id` was removed because no panel ever filtered by it (the
    column appears in SQL output but never in WHERE clauses); `tool_name` was
    removed because re-resolving its dependent ClickHouse query on every
    `session_id` change introduced a ~5 s wait per click without offering
    user-visible filter behavior. `call_id` lives on the dedicated
    `ploston-call-inspector` dashboard."""
    var_names = {v["name"] for v in dashboard.get("templating", {}).get("list", [])}
    assert var_names == {"session_id"}, (
        f"Expected only session_id as a template variable, got {var_names!r}. "
        "execution_id and tool_name were intentionally removed; do not "
        "reintroduce them without first proving the dependent-variable "
        "cascade no longer adds perceptible wait time."
    )


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


def test_recent_sessions_data_link_uses_hardcoded_slug(dashboard: dict) -> None:
    """The Recent Sessions row data link must reference the dashboard slug
    literally (`agent-session-inspector`) rather than the `${__dashboard.name}`
    macro.

    Grafana 11.6 / 12.x have an unresolved regression
    (`grafana/grafana#101453`, `#108426`, `#114826`) where same-dashboard data
    links built with `${__dashboard.name}` update the URL but fail to
    re-evaluate the panels — they sit on stale data until the next
    auto-refresh tick or a full page reload. Hard-coding the slug avoids the
    code path that triggers the bug. If this regression is ever fixed
    upstream, this test can be relaxed; until then, leaving the macro in
    place silently breaks click-through navigation."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Recent Sessions")
    overrides = panel.get("fieldConfig", {}).get("overrides", [])
    urls: list[str] = []
    for override in overrides:
        if override.get("matcher", {}).get("options") != "session_id":
            continue
        for prop in override.get("properties", []):
            if prop.get("id") != "links":
                continue
            for link in prop.get("value", []):
                urls.append(link.get("url", ""))
    assert urls, "Recent Sessions panel has no data links to inspect"
    for url in urls:
        assert "/agent-session-inspector?" in url or url.endswith("/agent-session-inspector"), (
            f"Data link {url!r} does not contain the literal slug "
            "'agent-session-inspector'. Re-introducing `${__dashboard.name}` "
            "regresses the Grafana 11.6/12.x click-through bug."
        )
        assert "${__dashboard.name}" not in url, (
            f"Data link {url!r} reintroduces the `${{__dashboard.name}}` "
            "macro that triggers Grafana's stale-panel bug "
            "(grafana/grafana#101453)."
        )


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


def test_centerpiece_query_does_not_filter_by_tool_name(dashboard: dict) -> None:
    """Regression guard: the Tool Call Timeline must NOT reintroduce a
    ``$tool_name`` template-variable filter.

    The `tool_name` variable was removed because re-resolving its dependent
    ClickHouse query on every `session_id` change introduced a ~5 s wait
    per drill-through click. The timeline now relies on the session_id WHERE
    clause alone; the per-tool breakdown lives in the `Tool Usage
    Distribution` pie chart."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Tool Call Timeline")
    sql = panel["targets"][0]["rawSql"]
    assert "$tool_name" not in sql, (
        "Tool Call Timeline SQL references $tool_name but the variable was "
        "intentionally removed; reintroducing the dependency reinstates the "
        "5 s wait on every session click."
    )


def test_events_panel_targets_ploston_events_view(dashboard: dict) -> None:
    """Panel 6 must query ploston.events (the SQL view over otel_logs)."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Free-form Events")
    sql = panel["targets"][0]["rawSql"]
    assert "ploston.events" in sql
    assert "session_id = '$session_id'" in sql


def test_tool_call_timeline_groups_wrapper_and_inner_calls(dashboard: dict) -> None:
    """Tool Call Timeline orders rows so wrapper invocations
    (``workflow_call_tool``, ``workflow_run``) are immediately followed by the
    inner tool calls that share their ``execution_id``, with the inner row's
    ``tool_name`` indented (``└─ ``).  The grouping uses an ``argMin`` window
    function over ``execution_id`` to pick the earliest call as the parent.
    Hidden helper columns (``depth``, ``group_key``, ``group_started_at``)
    drive the visual ordering and styling without being shown to the user."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Tool Call Timeline")
    sql = panel["targets"][0]["rawSql"]
    # Window function picks the parent of each execution_id partition.
    assert "argMin(call_id, started_at) OVER (PARTITION BY execution_id)" in sql
    # Children are visually indented with a tree glyph.
    assert "concat('└─ ', tool_name)" in sql
    # Group ordering uses the parent's started_at so groups stay chronological.
    assert "min(started_at) OVER (PARTITION BY group_key) AS group_started_at" in sql
    assert "ORDER BY group_started_at ASC, depth ASC, started_at ASC" in sql
    # Helper columns must be hidden from the visible table.
    overrides = panel.get("fieldConfig", {}).get("overrides", [])
    hidden_cols = {
        ov["matcher"]["options"]
        for ov in overrides
        if any(
            p.get("id") == "custom.hidden" and p.get("value") is True
            for p in ov.get("properties", [])
        )
    }
    assert {"depth", "group_key", "group_started_at"}.issubset(hidden_cols)


def test_tool_call_timeline_kind_distinguishes_wrapper_wrapped_direct(
    dashboard: dict,
) -> None:
    """The ``kind`` column must read 'wrapped' for child rows, 'wrapper' for
    parent rows whose tool is one of the dispatch wrappers, and 'direct' for
    everything else.  An earlier version used ``execution_id != ''`` as the
    discriminator, but every row now carries an ``execution_id`` (direct calls
    get their own one), which made every row read 'workflow' — the visible
    bug this assertion guards against."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Tool Call Timeline")
    sql = panel["targets"][0]["rawSql"]
    # Use multiIf so child rows are detected first via call_id != group_key,
    # then wrappers via the explicit dispatcher tool name list, else direct.
    assert (
        "multiIf(call_id != group_key, 'wrapped', "
        "tool_name IN ('workflow_call_tool','workflow_run'), 'wrapper', "
        "'direct') AS kind"
    ) in sql
    # The buggy heuristic must not regress.
    assert "if(execution_id != '', 'workflow', 'direct') AS kind" not in sql


def test_dashboard_dispatcher_list_matches_workflow_dispatcher_tool_names() -> None:
    """The hard-coded dispatcher list in the Session and Call Inspector SQL
    (``tool_name IN ('workflow_call_tool','workflow_run')``) must stay in sync
    with ``WORKFLOW_DISPATCHER_TOOL_NAMES`` defined in
    ``packages/ploston-core/src/ploston_core/workflow/tools.py``. If a third
    dispatcher is ever added there, this test fails until both dashboards'
    SQL is updated to match."""
    try:
        from ploston_core.workflow.tools import WORKFLOW_DISPATCHER_TOOL_NAMES
    except ImportError:
        pytest.skip("ploston_core not importable in this test environment")

    # Session Inspector — Tool Call Timeline panel
    with open(_DOCKER_PATH) as f:
        session_dashboard = json.load(f)
    timeline_panel = next(
        p for p in session_dashboard["panels"] if p.get("title") == "Tool Call Timeline"
    )
    timeline_sql = timeline_panel["targets"][0]["rawSql"]

    # Call Inspector — Call Header panel
    with open(_CALL_INSPECTOR_PATH) as f:
        call_dashboard = json.load(f)
    header_panel = next(p for p in call_dashboard["panels"] if p.get("title") == "Call Header")
    header_sql = header_panel["targets"][0]["rawSql"]

    expected = "(" + ",".join(f"'{name}'" for name in sorted(WORKFLOW_DISPATCHER_TOOL_NAMES)) + ")"
    for name in WORKFLOW_DISPATCHER_TOOL_NAMES:
        assert f"'{name}'" in timeline_sql, (
            f"Session Inspector Tool Call Timeline SQL is missing dispatcher "
            f"tool {name!r}; update the panel rawSql to include {expected}."
        )
        assert f"'{name}'" in header_sql, (
            f"Call Inspector Call Header SQL is missing dispatcher tool "
            f"{name!r}; update the panel rawSql to include {expected}."
        )
    # Both dashboards must use the same buggy-heuristic-free expression.
    assert "if(execution_id != '', 'workflow', 'direct') AS kind" not in header_sql


@pytest.fixture
def call_inspector() -> dict:
    with open(_CALL_INSPECTOR_PATH) as f:
        return json.load(f)


def test_call_inspector_has_session_id_and_call_id_dropdowns(
    call_inspector: dict,
) -> None:
    """Both template variables must be SQL-driven dropdowns; the textbox
    `call_id` was replaced so users can pick a call without pasting a UUID.
    `session_id` is upstream of `call_id` so the call list is scoped to the
    session, keeping the dropdown size manageable."""
    variables = {v["name"]: v for v in call_inspector["templating"]["list"]}
    assert set(variables) == {"session_id", "call_id"}
    for name in ("session_id", "call_id"):
        assert variables[name]["type"] == "query", (
            f"{name} variable must be a SQL-driven dropdown, not a textbox"
        )
        ds = variables[name].get("datasource") or {}
        assert ds.get("uid") == "clickhouse"
    # The `grafana-clickhouse-datasource` plugin uses column ORDER, not the
    # `__text`/`__value` alias convention: first column is the variable's
    # value (raw call_id UUID), second column is the displayed label
    # (HH:MM:SS tool_name (duration) [status]). Aliasing as __text/__value
    # silently produced an inverted variable that broke every panel query.
    call_query = variables["call_id"]["query"]
    assert call_query.startswith("SELECT call_id AS value,"), (
        "call_id variable must SELECT call_id first (value) then the display "
        "label second; the official ClickHouse plugin does not honor "
        "__text/__value aliases (see "
        "https://github.com/grafana/clickhouse-datasource/issues/264)."
    )
    # `formatDateTime` must use `%i` (minute) not `%M` (month) — common bug.
    assert "%i" in call_query


def test_call_inspector_has_stats_sibling_and_events_panels(
    call_inspector: dict,
) -> None:
    """The Call Inspector must include the deep-dive panels: Stats (timing
    and payload sizes), Sibling Calls (other rows sharing this execution_id),
    and Events (free-form events scoped by execution_id)."""
    titles = [p["title"] for p in call_inspector["panels"]]
    for required in (
        "Stats",
        "Call Header",
        "Sibling Calls",
        "Params",
        "Result",
        "Error",
        "Events",
    ):
        assert required in titles, f"Call Inspector missing {required!r} panel"


def test_sibling_calls_panel_filters_by_execution_id(call_inspector: dict) -> None:
    """The Sibling Calls panel must scope by the current call's execution_id
    so it shows only the parent + siblings, never unrelated rows."""
    panel = next(p for p in call_inspector["panels"] if p["title"] == "Sibling Calls")
    sql = panel["targets"][0]["rawSql"]
    assert "execution_id = (SELECT execution_id FROM" in sql
    assert "$call_id" in sql
    # Drill-down link routes back to the inspector with both vars propagated.
    overrides = panel["fieldConfig"]["overrides"]
    call_id_override = next(ov for ov in overrides if ov["matcher"]["options"] == "call_id")
    links = next(p["value"] for p in call_id_override["properties"] if p["id"] == "links")
    assert any("var-session_id=" in lk["url"] and "var-call_id=" in lk["url"] for lk in links)


def test_events_panel_filters_by_execution_id(call_inspector: dict) -> None:
    """The Events panel must scope by execution_id (events don't carry
    call_id today). For direct calls (1:1 with execution_id) the scope is
    exact; for wrapper calls it includes the wrapper + its child."""
    panel = next(p for p in call_inspector["panels"] if p["title"] == "Events")
    sql = panel["targets"][0]["rawSql"]
    assert "ploston.events" in sql
    assert (
        "execution_id = (SELECT execution_id FROM ploston.tool_calls WHERE call_id = '$call_id'"
        in sql
    )


def test_session_inspector_call_drilldown_propagates_session_id(
    dashboard: dict,
) -> None:
    """The Tool Call Timeline drill-down link to the Call Inspector must
    pass `var-session_id` so the call dropdown is pre-filtered correctly."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Tool Call Timeline")
    overrides = panel["fieldConfig"]["overrides"]
    call_id_override = next(ov for ov in overrides if ov["matcher"]["options"] == "call_id")
    links = next(p["value"] for p in call_id_override["properties"] if p["id"] == "links")
    assert any("var-session_id=" in lk["url"] and "var-call_id=" in lk["url"] for lk in links)
