"""Unit tests for bootstrap health module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ploston_cli.bootstrap import HealthCheckResult, HealthPoller


class TestHealthCheckResult:
    """Tests for HealthCheckResult dataclass."""

    def test_healthy_result(self):
        """Test creating a healthy result."""
        result = HealthCheckResult(
            healthy=True,
            version="1.0.0",
            elapsed_seconds=2.5,
        )
        assert result.healthy is True
        assert result.version == "1.0.0"
        assert result.elapsed_seconds == 2.5
        assert result.error is None

    def test_unhealthy_result(self):
        """Test creating an unhealthy result."""
        result = HealthCheckResult(
            healthy=False,
            error="Connection refused",
            elapsed_seconds=60.0,
        )
        assert result.healthy is False
        assert result.error == "Connection refused"


class TestHealthPoller:
    """Tests for HealthPoller."""

    def test_default_config(self):
        """Test default poller configuration."""
        poller = HealthPoller()
        assert poller.max_attempts == 30
        assert poller.interval_seconds == 2.0

    def test_custom_config(self):
        """Test custom poller configuration."""
        poller = HealthPoller(max_attempts=10, interval_seconds=1.0)
        assert poller.max_attempts == 10
        assert poller.interval_seconds == 1.0

    @pytest.mark.asyncio
    async def test_wait_for_healthy_success(self):
        """Test successful health check."""
        poller = HealthPoller(max_attempts=3, interval_seconds=0.1)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "ok", "version": "1.0.0"}
            mock_client.get.return_value = mock_response

            result = await poller.wait_for_healthy("http://localhost:8082")

            assert result.healthy is True
            assert result.version == "1.0.0"

    @pytest.mark.asyncio
    async def test_wait_for_healthy_timeout(self):
        """Test health check timeout."""
        poller = HealthPoller(max_attempts=2, interval_seconds=0.1)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = Exception("Connection refused")

            result = await poller.wait_for_healthy("http://localhost:8082")

            assert result.healthy is False
            assert result.error is not None

    @pytest.mark.asyncio
    async def test_wait_for_healthy_with_callback(self):
        """Test health check with progress callback."""
        poller = HealthPoller(max_attempts=3, interval_seconds=0.1)
        callback_calls = []

        def on_attempt(attempt, max_attempts, error):
            callback_calls.append((attempt, max_attempts, error))

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # First call fails, second succeeds
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "ok"}
            mock_client.get.side_effect = [
                Exception("Connection refused"),
                mock_response,
            ]

            result = await poller.wait_for_healthy(
                "http://localhost:8082",
                on_attempt=on_attempt,
            )

            assert result.healthy is True
            assert len(callback_calls) >= 1

    def test_sync_wrapper(self):
        """Test synchronous wrapper."""
        poller = HealthPoller(max_attempts=2, interval_seconds=0.1)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "ok", "version": "1.0.0"}
            mock_client.get.return_value = mock_response

            result = poller.wait_for_healthy_sync("http://localhost:8082")

            assert result.healthy is True
