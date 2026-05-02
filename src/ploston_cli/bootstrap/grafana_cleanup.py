"""Grafana datasource cleanup helper (DEC-194 / S-303 T-977).

Removes legacy Loki / Tempo datasources that linger in upgraded Grafana
volumes after M-082 swapped to ClickHouse. Idempotent via a marker file
under ``~/.ploston/observability/grafana/.cleanup_v1``; first-time
installs are unaffected.

The helper waits for Grafana's HTTP API to be reachable (``/api/health``
returning 200) before issuing DELETE calls, so the bootstrap flow can
call it immediately after the observability stack is up without racing
container start-up.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_MARKER = Path.home() / ".ploston" / "observability" / "grafana" / ".cleanup_v1"
_LEGACY_DATASOURCES = ("loki", "tempo")
# Polling shape mirrors HealthPoller defaults; Grafana boots in a few seconds
# but we keep headroom for slow hosts and image pulls on first run.
_READY_MAX_ATTEMPTS = 30
_READY_INTERVAL_SECONDS = 2.0
_HTTP_TIMEOUT_SECONDS = 5.0


def _wait_for_grafana(grafana_url: str) -> bool:
    """Block until ``GET {grafana_url}/api/health`` returns 200, bounded.

    Returns True if Grafana became reachable, False on timeout.
    """
    last_error: str | None = None
    for attempt in range(1, _READY_MAX_ATTEMPTS + 1):
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                resp = client.get(f"{grafana_url}/api/health")
                if resp.status_code == 200:
                    return True
                last_error = f"HTTP {resp.status_code}"
        except httpx.ConnectError:
            last_error = "connection refused"
        except httpx.TimeoutException:
            last_error = "request timeout"
        except Exception as e:
            last_error = str(e)
        if attempt < _READY_MAX_ATTEMPTS:
            time.sleep(_READY_INTERVAL_SECONDS)
    logger.warning(
        "Grafana did not become reachable at %s (last error: %s); skipping datasource cleanup",
        grafana_url,
        last_error,
    )
    return False


def cleanup_orphaned_grafana_datasources(
    grafana_url: str = "http://localhost:3000",
    admin_creds: tuple[str, str] = ("admin", "admin"),
    *,
    marker_path: Path | None = None,
) -> int:
    """Delete legacy Loki/Tempo datasources from upgraded Grafana volumes.

    Args:
        grafana_url: Base URL of the Grafana instance to clean (compose-host
            local default).
        admin_creds: ``(username, password)`` for Grafana basic auth. The OSS
            default is ``admin/admin`` and matches the bundled provisioning.
        marker_path: Override for the idempotency marker (tests).

    Returns:
        Number of datasources actually deleted on this call. Zero when the
        marker is already present, when the volume is fresh, or when Grafana
        was not reachable in time.
    """
    marker = marker_path or _DEFAULT_MARKER
    if marker.exists():
        logger.debug("Grafana datasource cleanup marker present at %s; skipping", marker)
        return 0

    if not _wait_for_grafana(grafana_url):
        # Don't write the marker — leave the volume in a state where the next
        # bootstrap pass can retry the cleanup.
        return 0

    deleted = 0
    with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS, auth=admin_creds) as client:
        for ds_name in _LEGACY_DATASOURCES:
            resp = client.delete(f"{grafana_url}/api/datasources/name/{ds_name}")
            if resp.status_code == 200:
                deleted += 1
            elif resp.status_code == 404:
                # Already absent (fresh install or earlier cleanup without marker).
                continue
            else:
                resp.raise_for_status()

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"v1\n{datetime.now(UTC).isoformat()}\n")
    if deleted:
        logger.info("Removed %d orphaned Grafana datasources from upgraded volume", deleted)
    return deleted
