"""Health polling for bootstrap command.

This module provides health endpoint polling to wait for
the Control Plane to become ready.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

import httpx


@dataclass
class HealthCheckResult:
    """Result of health check attempt."""

    healthy: bool
    version: str | None = None
    mode: str | None = None
    attempts: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None


class HealthPoller:
    """Poll CP health endpoint."""

    def __init__(
        self,
        max_attempts: int = 30,
        interval_seconds: float = 2.0,
        timeout_seconds: float = 5.0,
    ):
        """Initialize health poller.

        Args:
            max_attempts: Maximum number of health check attempts.
            interval_seconds: Seconds between attempts.
            timeout_seconds: Timeout for each HTTP request.
        """
        self.max_attempts = max_attempts
        self.interval_seconds = interval_seconds
        self.timeout_seconds = timeout_seconds

    async def wait_for_healthy(
        self,
        url: str = "http://localhost:8082",
        on_attempt: callable | None = None,
    ) -> HealthCheckResult:
        """Poll health endpoint until healthy or timeout.

        Args:
            url: Base URL of the Control Plane.
            on_attempt: Optional callback called with (attempt, max_attempts, error)
                       for progress reporting.

        Returns:
            HealthCheckResult with status information.
        """
        start = datetime.now()
        last_error: str | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.get(f"{url}/health")
                    if response.status_code == 200:
                        data = response.json()
                        elapsed = (datetime.now() - start).total_seconds()
                        return HealthCheckResult(
                            healthy=True,
                            version=data.get("version"),
                            mode=data.get("mode"),
                            attempts=attempt,
                            elapsed_seconds=elapsed,
                        )
                    else:
                        last_error = f"HTTP {response.status_code}"
            except httpx.ConnectError:
                last_error = "Connection refused"
            except httpx.TimeoutException:
                last_error = "Request timeout"
            except Exception as e:
                last_error = str(e)

            # Report progress
            if on_attempt:
                on_attempt(attempt, self.max_attempts, last_error)

            # Wait before next attempt (unless this was the last one)
            if attempt < self.max_attempts:
                await asyncio.sleep(self.interval_seconds)

        elapsed = (datetime.now() - start).total_seconds()
        return HealthCheckResult(
            healthy=False,
            attempts=self.max_attempts,
            elapsed_seconds=elapsed,
            error=f"CP did not become healthy within timeout. Last error: {last_error}",
        )

    def wait_for_healthy_sync(
        self,
        url: str = "http://localhost:8082",
        on_attempt: callable | None = None,
    ) -> HealthCheckResult:
        """Synchronous wrapper for wait_for_healthy.

        Args:
            url: Base URL of the Control Plane.
            on_attempt: Optional callback for progress reporting.

        Returns:
            HealthCheckResult with status information.
        """
        return asyncio.run(self.wait_for_healthy(url, on_attempt))
