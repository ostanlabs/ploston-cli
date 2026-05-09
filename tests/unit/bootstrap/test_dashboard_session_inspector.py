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


def test_tool_call_timeline_has_execution_id_drill_link(dashboard: dict) -> None:
    """Panel 3 must have a data link on ``execution_id`` for drill-down."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Tool Call Timeline")
    overrides = panel.get("fieldConfig", {}).get("overrides", [])
    found = False
    for override in overrides:
        if override.get("matcher", {}).get("options") == "execution_id":
            for prop in override.get("properties", []):
                if prop.get("id") == "links":
                    found = True
    assert found, "Tool Call Timeline panel missing execution_id data link"


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


def test_tool_call_timeline_shows_all_agent_visible_sources(dashboard: dict) -> None:
    """Tool Call Timeline includes ``direct``, ``wrapper``, and ``wrapped``
    rows so the user sees the full dispatch picture.  Workflow-internal
    steps (``tool_step`` / ``code_block``) are still excluded."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Tool Call Timeline")
    sql = panel["targets"][0]["rawSql"]
    assert "source IN ('direct', 'wrapper', 'wrapped')" in sql
    assert "splitByString('__', tool_name)" in sql
    assert "AS mcp_server" in sql
    assert "ORDER BY started_at ASC" in sql


def test_tool_call_timeline_wrapped_rows_have_tree_prefix(
    dashboard: dict,
) -> None:
    """Wrapped rows are visually nested with a ``└── `` prefix on the
    tool_name so the timeline shows hierarchy."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Tool Call Timeline")
    sql = panel["targets"][0]["rawSql"]
    assert "source = 'wrapped'" in sql
    assert "└── " in sql


def test_tool_call_timeline_kind_reflects_source(
    dashboard: dict,
) -> None:
    """The ``kind`` column uses the ``source`` column directly so that
    wrapper rows display as ``wrapper`` and direct rows as ``direct``."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Tool Call Timeline")
    sql = panel["targets"][0]["rawSql"]
    assert "source AS kind" in sql
    # Old grouping heuristics must not regress.
    assert "if(execution_id != '', 'workflow', 'direct') AS kind" not in sql
    assert "call_id != group_key" not in sql


def test_aggregation_panels_have_correct_source_filters(dashboard: dict) -> None:
    """Each aggregation panel uses the correct source filter per the
    accounting rules:

    - Tool Calls count: direct + wrapped (wrapper is plumbing, not a tool)
    - Tokens / Duration: direct + wrapper (wrapper carries the agent-facing
      payload; wrapped is already included in the wrapper's response_bytes)
    - Errors: all three (any source can error)
    - Unique Tools / Distribution: direct + wrapped
    - Recent Sessions: all three, with countIf to exclude wrappers from
      tool_calls and unique_tools counts
    """
    expected_filters: dict[str, str] = {
        "Tool Calls": "source IN ('direct', 'wrapped')",
        "Total Response (~tokens)": "source IN ('direct', 'wrapper')",
        "Total Duration": "source IN ('direct', 'wrapper')",
        "Unique Tools": "source IN ('direct', 'wrapped')",
        "Tool Usage Distribution": "source IN ('direct', 'wrapped')",
        "Errors": "source IN ('direct', 'wrapped', 'wrapper')",
    }

    all_panels = list(dashboard.get("panels", []))
    for panel in dashboard.get("panels", []):
        if panel.get("type") == "row":
            all_panels.extend(panel.get("panels", []))

    for panel in all_panels:
        title = panel.get("title", "")
        if title in expected_filters:
            expected = expected_filters[title]
            for target in panel.get("targets", []):
                sql = target.get("rawSql", "")
                if not sql:
                    continue
                assert expected in sql, (
                    f"Panel {title!r} must contain ``{expected}`` but the SQL is:\n{sql}"
                )


def test_recent_sessions_uses_conditional_counts(dashboard: dict) -> None:
    """Recent Sessions includes all three sources but uses countIf to
    exclude wrappers from tool_calls and unique_tools (wrappers are
    plumbing, not agent-visible tools)."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Recent Sessions")
    sql = panel["targets"][0]["rawSql"]
    assert "source IN ('direct', 'wrapped', 'wrapper')" in sql
    assert "countIf(source != 'wrapper') AS tool_calls" in sql
    assert "countDistinctIf(tool_name, source != 'wrapper') AS unique_tools" in sql


def test_call_inspector_uses_source_wrapper_for_dispatcher_detection() -> None:
    """The Call Inspector Call Header SQL must use ``source = 'wrapper'``
    to identify dispatcher rows, NOT a hard-coded tool_name IN (...) list.

    Dispatcher tools (workflow_call_tool, workflow_run) now write
    ``source = 'wrapper'`` in telemetry, so the dashboard can identify
    them without maintaining a fragile name list."""
    with open(_CALL_INSPECTOR_PATH) as f:
        call_dashboard = json.load(f)
    header_panel = next(p for p in call_dashboard["panels"] if p.get("title") == "Call Header")
    header_sql = header_panel["targets"][0]["rawSql"]

    # New: source-based detection
    assert "source = 'wrapper'" in header_sql, (
        "Call Inspector Call Header SQL must use source = 'wrapper' to detect dispatcher rows."
    )
    # Old hard-coded list must be gone
    assert "tool_name IN (" not in header_sql, (
        "Call Inspector Call Header SQL should no longer use a hard-coded "
        "tool_name IN (...) list for dispatcher detection."
    )
    # Buggy heuristic must not regress.
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


def test_session_inspector_execution_id_drilldown(
    dashboard: dict,
) -> None:
    """The Tool Call Timeline ``execution_id`` column must have a data link
    so the user can navigate to the Call Inspector for deeper investigation."""
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Tool Call Timeline")
    overrides = panel["fieldConfig"]["overrides"]
    exec_id_override = next(ov for ov in overrides if ov["matcher"]["options"] == "execution_id")
    links = next(p["value"] for p in exec_id_override["properties"] if p["id"] == "links")
    assert len(links) >= 1, "execution_id must have at least one data link"
