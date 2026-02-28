"""Onboarding scenarios — first-time setup and verification.

S-01: Install & verify version (Layer 1 — no Docker)
S-02: Start CP & health check (Layer 2 — Docker Compose)
S-03: Server info & capabilities (Layer 2 — Docker Compose)
"""

from __future__ import annotations

import pytest
import requests

# ── S-01: Install & verify version ──────────────────────────────────


@pytest.mark.scenario
class TestS01InstallAndVersion:
    """S-01: User installs ploston-cli and checks version."""

    def test_version_command_exits_zero(self, cli):
        """ploston version exits 0 (even if server unavailable)."""
        result = cli("version", check=False)
        # Version command should exit 0 even if server is unavailable
        assert result.returncode == 0, (
            f"S-01: version should exit 0, got {result.returncode}. stderr: {result.stderr}"
        )

    def test_version_output_contains_cli_version(self, cli):
        """ploston version outputs CLI version string."""
        result = cli("version", check=False)
        # Should contain "Ploston CLI version" or similar
        output = result.stdout + result.stderr
        assert "version" in output.lower() or "1.0.0" in output, (
            f"S-01: version output should contain version info, got: {output}"
        )

    def test_help_command_exits_zero(self, cli):
        """ploston --help exits 0 and shows usage."""
        result = cli("--help")
        assert "usage" in result.stdout.lower() or "Usage" in result.stdout, (
            "S-01: --help should show usage info"
        )

    def test_init_subcommand_in_help(self, cli):
        """ploston --help lists the init subcommand."""
        result = cli("--help", check=False)
        assert result.returncode == 0
        assert "init" in result.stdout.lower(), "S-01: --help should list 'init' subcommand"

    def test_init_help_available(self, cli):
        """ploston init --help shows init command help."""
        result = cli("init", "--help", check=False)
        assert result.returncode == 0
        assert "--import" in result.stdout, "init --help should document --import flag"


# ── S-02: Start CP & health check ──────────────────────────────────


@pytest.mark.scenario
@pytest.mark.docker
class TestS02HealthCheck:
    """S-02: User starts CP and verifies health."""

    def test_health_endpoint_returns_200(self, cp_url):
        """GET /health returns 200."""
        response = requests.get(f"{cp_url}/health", timeout=10)
        assert response.status_code == 200, (
            f"S-02: /health should return 200, got {response.status_code}"
        )

    def test_health_reports_all_healthy(self, cp_url):
        """Health response shows all checks healthy."""
        response = requests.get(f"{cp_url}/health", timeout=10)
        data = response.json()
        assert data.get("status") == "healthy", (
            f"S-02: status should be 'healthy', got {data.get('status')}"
        )

    def test_api_health_endpoint(self, api_url):
        """GET /api/v1/health also works."""
        response = requests.get(f"{api_url}/health", timeout=10)
        assert response.status_code == 200


# ── S-03: Server info & capabilities ───────────────────────────────


@pytest.mark.scenario
@pytest.mark.docker
class TestS03ServerInfo:
    """S-03: User queries server info and capabilities."""

    def test_info_endpoint_returns_edition(self, api_url):
        """GET /api/v1/info returns edition field."""
        response = requests.get(f"{api_url}/info", timeout=10)
        data = response.json()
        assert "edition" in data, "S-03: info should contain 'edition'"
        assert data["edition"] == "oss", f"S-03: edition should be 'oss', got {data['edition']}"

    def test_info_returns_version(self, api_url):
        """Info response includes version."""
        response = requests.get(f"{api_url}/info", timeout=10)
        data = response.json()
        assert "version" in data, "S-03: info should contain 'version'"

    def test_info_returns_features(self, api_url):
        """Info response includes features object."""
        response = requests.get(f"{api_url}/info", timeout=10)
        data = response.json()
        assert "features" in data, "S-03: info should contain 'features'"
