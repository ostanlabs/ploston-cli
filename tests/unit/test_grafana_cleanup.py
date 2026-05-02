"""S-303 T-977: Grafana datasource cleanup helper.

Asserts the marker-file idempotency contract from DEC-194 plus the
correct HTTP semantics: list datasources, filter by ``type ∈ {loki,
tempo}``, DELETE by ``uid``, and skip everything once the marker is in
place.

Network calls are stubbed end-to-end; the helper must not touch a real
Grafana instance from the unit suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from ploston_cli.bootstrap import grafana_cleanup
from ploston_cli.bootstrap.grafana_cleanup import cleanup_orphaned_grafana_datasources


class _StubResponse:
    def __init__(self, status_code: int, json_body: Any = None) -> None:
        self.status_code = status_code
        self._json = json_body

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "stub",
                request=None,
                response=None,  # type: ignore[arg-type]
            )


class _StubClient:
    """Drop-in for ``httpx.Client`` recording GETs and DELETEs."""

    def __init__(
        self,
        listing: list[dict[str, Any]] | None = None,
        delete_status: dict[str, int] | None = None,
        **kwargs: Any,
    ) -> None:
        self.listing = listing or []
        self.delete_status = delete_status or {}
        self.gets: list[str] = []
        self.deletes: list[str] = []
        self.auth = kwargs.get("auth")

    def __enter__(self) -> "_StubClient":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def get(self, url: str) -> _StubResponse:
        self.gets.append(url)
        return _StubResponse(200, json_body=self.listing)

    def delete(self, url: str) -> _StubResponse:
        self.deletes.append(url)
        for uid, status in self.delete_status.items():
            if url.endswith(f"/api/datasources/uid/{uid}"):
                return _StubResponse(status)
        return _StubResponse(404)


def _ds(uid: str, name: str, ds_type: str) -> dict[str, Any]:
    return {"uid": uid, "name": name, "type": ds_type}


@pytest.fixture
def fake_marker(tmp_path: Path) -> Path:
    return tmp_path / ".cleanup_v1"


def _patch_ready(monkeypatch: pytest.MonkeyPatch, ready: bool = True) -> None:
    monkeypatch.setattr(grafana_cleanup, "_wait_for_grafana", lambda url: ready)


def test_first_call_deletes_both_datasources_and_writes_marker(
    monkeypatch: pytest.MonkeyPatch, fake_marker: Path
) -> None:
    """End-to-end happy path: list returns Loki+Tempo+ClickHouse; only the
    legacy two get deleted and the marker is committed."""
    _patch_ready(monkeypatch)
    captured: list[_StubClient] = []

    def factory(*args: Any, **kwargs: Any) -> _StubClient:
        c = _StubClient(
            listing=[
                _ds("loki", "Loki", "loki"),
                _ds("tempo", "Tempo", "tempo"),
                _ds("ch", "ClickHouse", "grafana-clickhouse-datasource"),
            ],
            delete_status={"loki": 200, "tempo": 200},
            **kwargs,
        )
        captured.append(c)
        return c

    monkeypatch.setattr(grafana_cleanup.httpx, "Client", factory)
    deleted = cleanup_orphaned_grafana_datasources(marker_path=fake_marker)
    assert deleted == 2
    assert fake_marker.exists()
    assert captured[0].auth == ("admin", "ploston")
    assert captured[0].gets == ["http://localhost:3000/api/datasources"]
    assert any("/uid/loki" in url for url in captured[0].deletes)
    assert any("/uid/tempo" in url for url in captured[0].deletes)
    # ClickHouse must never be touched.
    assert not any("/uid/ch" in url for url in captured[0].deletes)


def test_marker_present_skips_all_calls(monkeypatch: pytest.MonkeyPatch, fake_marker: Path) -> None:
    fake_marker.parent.mkdir(parents=True, exist_ok=True)
    fake_marker.write_text("v1\nprior-run\n")

    def factory(*args: Any, **kwargs: Any) -> _StubClient:
        raise AssertionError("Client must not be constructed when marker exists")

    monkeypatch.setattr(grafana_cleanup.httpx, "Client", factory)
    monkeypatch.setattr(grafana_cleanup, "_wait_for_grafana", lambda url: True)
    deleted = cleanup_orphaned_grafana_datasources(marker_path=fake_marker)
    assert deleted == 0


def test_fresh_install_writes_marker_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch, fake_marker: Path
) -> None:
    """Fresh install: listing has no legacy datasources; marker still committed
    so subsequent bootstrap passes don't repeat the work."""
    _patch_ready(monkeypatch)

    def factory(*args: Any, **kwargs: Any) -> _StubClient:
        return _StubClient(
            listing=[_ds("ch", "ClickHouse", "grafana-clickhouse-datasource")],
        )

    monkeypatch.setattr(grafana_cleanup.httpx, "Client", factory)
    deleted = cleanup_orphaned_grafana_datasources(marker_path=fake_marker)
    assert deleted == 0
    assert fake_marker.exists()


def test_grafana_unreachable_skips_without_marker(
    monkeypatch: pytest.MonkeyPatch, fake_marker: Path
) -> None:
    _patch_ready(monkeypatch, ready=False)

    def factory(*args: Any, **kwargs: Any) -> _StubClient:
        raise AssertionError("Client must not be constructed when Grafana is unreachable")

    monkeypatch.setattr(grafana_cleanup.httpx, "Client", factory)
    deleted = cleanup_orphaned_grafana_datasources(marker_path=fake_marker)
    assert deleted == 0
    # Marker NOT written, so the next bootstrap pass can retry.
    assert not fake_marker.exists()


def test_only_loki_present_writes_marker_and_returns_one(
    monkeypatch: pytest.MonkeyPatch, fake_marker: Path
) -> None:
    """Volumes from intermediate states may carry only Loki or only Tempo."""
    _patch_ready(monkeypatch)

    def factory(*args: Any, **kwargs: Any) -> _StubClient:
        return _StubClient(
            listing=[_ds("loki", "Loki", "loki")],
            delete_status={"loki": 200},
        )

    monkeypatch.setattr(grafana_cleanup.httpx, "Client", factory)
    deleted = cleanup_orphaned_grafana_datasources(marker_path=fake_marker)
    assert deleted == 1
    assert fake_marker.exists()


def test_renamed_legacy_datasource_still_deleted(
    monkeypatch: pytest.MonkeyPatch, fake_marker: Path
) -> None:
    """Filtering by ``type`` (not ``name``) catches user-renamed legacy
    datasources from upgraded volumes."""
    _patch_ready(monkeypatch)

    def factory(*args: Any, **kwargs: Any) -> _StubClient:
        return _StubClient(
            listing=[_ds("loki-old", "logs-old", "loki")],
            delete_status={"loki-old": 200},
        )

    monkeypatch.setattr(grafana_cleanup.httpx, "Client", factory)
    deleted = cleanup_orphaned_grafana_datasources(marker_path=fake_marker)
    assert deleted == 1
    assert fake_marker.exists()


def test_admin_creds_override_propagates_to_client(
    monkeypatch: pytest.MonkeyPatch, fake_marker: Path
) -> None:
    _patch_ready(monkeypatch)
    captured: list[_StubClient] = []

    def factory(*args: Any, **kwargs: Any) -> _StubClient:
        c = _StubClient(listing=[], **kwargs)
        captured.append(c)
        return c

    monkeypatch.setattr(grafana_cleanup.httpx, "Client", factory)
    cleanup_orphaned_grafana_datasources(admin_creds=("ops", "rotated"), marker_path=fake_marker)
    assert captured[0].auth == ("ops", "rotated")
