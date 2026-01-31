"""Tests for MockRestServer test utility.

Implements S-189: Test Infrastructure
- UT-117: MockRestServer initialization
- UT-118: MockRestServer runner endpoints
- UT-119: MockRestServer helper methods
"""

import pytest

from tests.mocks.mock_rest_server import MockRestServer


class TestMockRestServerInit:
    """Tests for MockRestServer initialization (UT-117)."""

    def test_init_creates_app(self):
        """Test that init creates FastAPI app."""
        server = MockRestServer()
        assert server.app is not None
        assert server.created_runners == {}
        assert server.tools == []

    def test_get_test_client(self):
        """Test that get_test_client returns TestClient."""
        server = MockRestServer()
        client = server.get_test_client()
        assert client is not None


class TestMockRestServerRunnerEndpoints:
    """Tests for MockRestServer runner endpoints (UT-118)."""

    def test_create_runner(self):
        """Test POST /api/v1/runners creates runner."""
        server = MockRestServer()
        client = server.get_test_client()

        response = client.post("/api/v1/runners", json={"name": "test-runner"})

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "test-runner"
        assert data["token"].startswith("plr_")
        assert data["status"] == "pending"
        assert "install_command" in data

    def test_create_runner_with_mcps(self):
        """Test POST /api/v1/runners with MCPs."""
        server = MockRestServer()
        client = server.get_test_client()

        response = client.post("/api/v1/runners", json={
            "name": "test-runner",
            "mcps": ["mcp1", "mcp2"]
        })

        assert response.status_code == 201
        data = response.json()
        assert data["mcps"] == ["mcp1", "mcp2"]

    def test_create_runner_duplicate(self):
        """Test POST /api/v1/runners with duplicate name."""
        server = MockRestServer()
        client = server.get_test_client()

        client.post("/api/v1/runners", json={"name": "test-runner"})
        response = client.post("/api/v1/runners", json={"name": "test-runner"})

        assert response.status_code == 409

    def test_list_runners_empty(self):
        """Test GET /api/v1/runners with no runners."""
        server = MockRestServer()
        client = server.get_test_client()

        response = client.get("/api/v1/runners")

        assert response.status_code == 200
        data = response.json()
        assert data["runners"] == []
        assert data["total"] == 0

    def test_list_runners_with_data(self):
        """Test GET /api/v1/runners with runners."""
        server = MockRestServer()
        client = server.get_test_client()

        client.post("/api/v1/runners", json={"name": "runner1"})
        client.post("/api/v1/runners", json={"name": "runner2"})

        response = client.get("/api/v1/runners")

        assert response.status_code == 200
        data = response.json()
        assert len(data["runners"]) == 2
        assert data["total"] == 2

    def test_get_runner(self):
        """Test GET /api/v1/runners/{name}."""
        server = MockRestServer()
        client = server.get_test_client()

        client.post("/api/v1/runners", json={"name": "test-runner"})
        response = client.get("/api/v1/runners/test-runner")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-runner"

    def test_get_runner_not_found(self):
        """Test GET /api/v1/runners/{name} not found."""
        server = MockRestServer()
        client = server.get_test_client()

        response = client.get("/api/v1/runners/nonexistent")

        assert response.status_code == 404

    def test_delete_runner(self):
        """Test DELETE /api/v1/runners/{name}."""
        server = MockRestServer()
        client = server.get_test_client()

        client.post("/api/v1/runners", json={"name": "test-runner"})
        response = client.delete("/api/v1/runners/test-runner")

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True

        # Verify deleted
        response = client.get("/api/v1/runners/test-runner")
        assert response.status_code == 404

    def test_delete_runner_not_found(self):
        """Test DELETE /api/v1/runners/{name} not found."""
        server = MockRestServer()
        client = server.get_test_client()

        response = client.delete("/api/v1/runners/nonexistent")

        assert response.status_code == 404


class TestMockRestServerHelpers:
    """Tests for MockRestServer helper methods (UT-119)."""

    def test_add_runner(self):
        """Test add_runner helper method."""
        server = MockRestServer()
        client = server.get_test_client()

        runner = server.add_runner("test-runner", status="connected", tools=["tool1"])

        assert runner["name"] == "test-runner"
        assert runner["status"] == "connected"
        assert runner["available_tools"] == ["tool1"]

        # Verify via API
        response = client.get("/api/v1/runners/test-runner")
        assert response.status_code == 200

    def test_add_tool(self):
        """Test add_tool helper method."""
        server = MockRestServer()
        client = server.get_test_client()

        tool = server.add_tool("test-tool", description="A test tool")

        assert tool["name"] == "test-tool"
        assert tool["description"] == "A test tool"

        # Verify via API
        response = client.get("/api/v1/tools")
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) == 1

    def test_clear(self):
        """Test clear helper method."""
        server = MockRestServer()
        client = server.get_test_client()

        server.add_runner("runner1")
        server.add_tool("tool1")
        server.clear()

        response = client.get("/api/v1/runners")
        assert response.json()["total"] == 0

        response = client.get("/api/v1/tools")
        assert response.json()["total"] == 0
