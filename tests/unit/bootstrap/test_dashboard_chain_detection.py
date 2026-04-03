"""Dashboard chain-detection JSON validation tests (Tier 1)."""

import json
import os

import pytest

# Resolve the Docker dashboard path relative to the ploston-cli package root,
# so the test works both inside the monorepo and in standalone CI checkouts.
_PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
_DOCKER_PATH = os.path.join(
    _PKG_ROOT,
    "src/ploston_cli/bootstrap/assets/docker/observability/grafana/dashboards/chain-detection.json",
)
# Helm chart path only exists in the monorepo layout.
_MONOREPO_ROOT = os.path.abspath(os.path.join(_PKG_ROOT, "../.."))
_HELM_PATH = os.path.join(
    _MONOREPO_ROOT, "charts/ploston-observability/dashboards/chain-detection.json"
)


@pytest.fixture
def chain_detection_json():
    with open(_DOCKER_PATH) as f:
        return json.load(f)


def test_no_hardcoded_24h_ranges(chain_detection_json):
    for panel in chain_detection_json["panels"]:
        for target in panel.get("targets", []):
            assert "[24h]" not in target.get("expr", ""), (
                f"Panel '{panel['title']}' still has hardcoded [24h]"
            )


def test_all_chain_link_panels_use_range_variable(chain_detection_json):
    for panel in chain_detection_json["panels"]:
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            if "ploston_chain_links_total" in expr:
                # rate() panels legitimately use fixed windows (e.g. [5m])
                if "rate(" not in expr:
                    assert "[$__range]" in expr


def test_bridge_id_variable_wired_in_chain_link_panels(chain_detection_json):
    for panel in chain_detection_json["panels"]:
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            if "ploston_chain_links_total" in expr:
                assert 'bridge_id=~"$bridge_id"' in expr


def test_workflow_variable_removed(chain_detection_json):
    variables = chain_detection_json["templating"]["list"]
    names = [v["name"] for v in variables]
    assert "workflow" not in names, (
        "$workflow variable must be removed — workflow_id is not emitted on chain metrics"
    )


def test_token_savings_panel_uses_real_metric(chain_detection_json):
    savings_panel = next(
        p
        for p in chain_detection_json["panels"]
        if "savings" in p["title"].lower() or "token" in p["title"].lower()
    )
    expr = savings_panel["targets"][0]["expr"]
    assert "ploston_tokens_saved_total" in expr
    assert "* 1500" not in expr


def test_unique_chains_panel_is_time_windowed(chain_detection_json):
    chains_panel = next(p for p in chain_detection_json["panels"] if "unique" in p["title"].lower())
    expr = chains_panel["targets"][0]["expr"]
    assert "increase(" in expr
    assert "> 0" in expr


def test_top_chain_candidates_panel_is_time_windowed(chain_detection_json):
    panel = next(p for p in chain_detection_json["panels"] if "candidate" in p["title"].lower())
    expr = panel["targets"][0]["expr"]
    assert "[$__range]" in expr, "Top Chain Candidates panel must use [$__range] time macro"


@pytest.mark.skipif(
    not os.path.exists(_HELM_PATH),
    reason="Helm chart path not available (standalone checkout)",
)
def test_both_dashboard_copies_are_identical():
    with open(_DOCKER_PATH) as f:
        docker_json = json.load(f)
    with open(_HELM_PATH) as f:
        helm_json = json.load(f)
    assert docker_json == helm_json, (
        "Dashboard copies have diverged — sync helm chart from docker copy"
    )
