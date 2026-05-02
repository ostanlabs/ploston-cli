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
# Datasource ``type`` values (lowercase per Grafana API) we want gone after the
# M-082 ClickHouse switchover. Filtering by type instead of name avoids
# guessing case (``Loki`` vs ``loki``) and tolerates user-renamed datasources.
_LEGACY_TYPES = ("loki", "tempo")
# Default Grafana admin password matches GF_SECURITY_ADMIN_PASSWORD in the
# bootstrap compose overlay. The helper accepts an override for K8s/custom
# stacks that rotate it.
_DEFAULT_ADMIN_CREDS = ("admin", "ploston")
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
    admin_creds: tuple[str, str] = _DEFAULT_ADMIN_CREDS,
    *,
    marker_path: Path | None = None,
) -> int:
    """Delete legacy Loki/Tempo datasources from upgraded Grafana volumes.

    The helper enumerates ``/api/datasources`` and deletes by ``uid`` for any
    datasource whose ``type`` is in :data:`_LEGACY_TYPES`. This is robust to
    renamed datasources and to Grafana's case-sensitive ``/name/`` lookup.

    Args:
        grafana_url: Base URL of the Grafana instance to clean (compose-host
            local default).
        admin_creds: ``(username, password)`` for Grafana basic auth. The OSS
            default is ``admin/ploston`` and matches the bundled provisioning;
            override for K8s/custom stacks that rotate the password.
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
        list_resp = client.get(f"{grafana_url}/api/datasources")
        list_resp.raise_for_status()
        datasources = list_resp.json() or []
        targets = [
            (ds.get("uid"), ds.get("name"), ds.get("type"))
            for ds in datasources
            if ds.get("type") in _LEGACY_TYPES and ds.get("uid")
        ]
        for uid, name, ds_type in targets:
            del_resp = client.delete(f"{grafana_url}/api/datasources/uid/{uid}")
            if del_resp.status_code == 200:
                deleted += 1
                logger.info("Deleted legacy Grafana datasource: %s (%s)", name, ds_type)
            elif del_resp.status_code == 404:
                # Raced with another cleanup; treat as already gone.
                continue
            else:
                del_resp.raise_for_status()

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"v1\n{datetime.now(UTC).isoformat()}\n")
    if deleted:
        logger.info("Removed %d orphaned Grafana datasources from upgraded volume", deleted)
    return deleted
