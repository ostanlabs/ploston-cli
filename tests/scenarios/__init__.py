"""Scenario tests for ploston-cli.

These tests validate end-to-end user journeys across CLI, bridge, runner,
and control plane. They are organized by the USER_SCENARIO_AUTOMATION_MAP.md
document (S-01 through S-44).

Layers:
  Layer 1 (no backend): S-01, S-04, S-05, S-42, S-43 — pure CLI, no Docker
  Layer 2 (Docker Compose): S-02 through S-41, S-44 — CP + mock MCPs
"""
