"""Capabilities client for tier detection.

This module provides the client for fetching and caching server capabilities,
enabling tier-aware command behavior.
"""

from dataclasses import dataclass
from typing import Any, Optional

import httpx


@dataclass
class ServerCapabilities:
    """Server capabilities response."""

    tier: str  # "community" or "enterprise"
    version: str
    features: dict[str, bool]
    limits: dict[str, Any]
    license: Optional[dict[str, Any]] = None

    def is_enterprise(self) -> bool:
        return self.tier == "enterprise"

    def is_feature_enabled(self, feature: str) -> bool:
        return self.features.get(feature, False)


class CapabilitiesClient:
    """Client for fetching and caching server capabilities."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._cached: Optional[ServerCapabilities] = None

    async def fetch(self, force_refresh: bool = False) -> ServerCapabilities:
        """Fetch capabilities from server.

        Caches result for duration of CLI execution.

        Args:
            force_refresh: If True, bypass cache and fetch fresh data.

        Returns:
            ServerCapabilities with tier, features, and limits.

        Raises:
            ConnectionError: If cannot connect to server.
            RuntimeError: If server returns an error.
        """
        if self._cached and not force_refresh:
            return self._cached

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/api/v1/capabilities",
                    timeout=5.0,
                )
                response.raise_for_status()
                data = response.json()

                self._cached = ServerCapabilities(
                    tier=data["tier"],
                    version=data["version"],
                    features=data["features"],
                    limits=data["limits"],
                    license=data.get("license"),
                )
                return self._cached

            except httpx.ConnectError:
                raise ConnectionError(
                    f"Cannot connect to Ploston server at {self.base_url}\n"
                    f"Is the server running? Try: ploston serve"
                )
            except httpx.HTTPStatusError as e:
                raise RuntimeError(f"Server error: {e.response.status_code}")
