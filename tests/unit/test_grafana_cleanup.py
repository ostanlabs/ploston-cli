"""S-303 T-977: Grafana datasource cleanup helper.

Asserts the marker-file idempotency contract from DEC-194 plus the
correct HTTP semantics: DELETE both legacy datasources, treat 404 as
already-absent, and skip everything once the marker is in place.

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
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "stub",
                request=None,
                response=None,  # type: ignore[arg-type]
            )


class _StubClient:
    """Drop-in for ``httpx.Client`` capturing every DELETE issued."""

    def __init__(
        self,
        delete_status: dict[str, int] | None = None,
        **_: Any,
    ) -> None:
        self.delete_status = delete_status or {}
        self.deletes: list[str] = []

    def __enter__(self) -> "_StubClient":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def delete(self, url: str) -> _StubResponse:
        self.deletes.append(url)
        for name, status in self.delete_status.items():
            if url.endswith(f"/api/datasources/name/{name}"):
                return _StubResponse(status)
        return _StubResponse(404)


@pytest.fixture
def fake_marker(tmp_path: Path) -> Path:
    return tmp_path / ".cleanup_v1"


def _patch_ready(monkeypatch: pytest.MonkeyPatch, ready: bool = True) -> None:
    monkeypatch.setattr(grafana_cleanup, "_wait_for_grafana", lambda url: ready)


def test_first_call_deletes_both_datasources_and_writes_marker(
    monkeypatch: pytest.MonkeyPatch, fake_marker: Path
) -> None:
    _patch_ready(monkeypatch)
    captured: list[_StubClient] = []

    def factory(*args: Any, **kwargs: Any) -> _StubClient:
        c = _StubClient(delete_status={"loki": 200, "tempo": 200})
        captured.append(c)
        return c

    monkeypatch.setattr(grafana_cleanup.httpx, "Client", factory)
    deleted = cleanup_orphaned_grafana_datasources(marker_path=fake_marker)
    assert deleted == 2
    assert fake_marker.exists()
    assert any("loki" in url for url in captured[0].deletes)
    assert any("tempo" in url for url in captured[0].deletes)


def test_marker_present_skips_all_deletes(
    monkeypatch: pytest.MonkeyPatch, fake_marker: Path
) -> None:
    fake_marker.parent.mkdir(parents=True, exist_ok=True)
    fake_marker.write_text("v1\nprior-run\n")

    def factory(*args: Any, **kwargs: Any) -> _StubClient:
        raise AssertionError("Client must not be constructed when marker exists")

    monkeypatch.setattr(grafana_cleanup.httpx, "Client", factory)
    monkeypatch.setattr(grafana_cleanup, "_wait_for_grafana", lambda url: True)
    deleted = cleanup_orphaned_grafana_datasources(marker_path=fake_marker)
    assert deleted == 0


def test_404_treated_as_already_absent(monkeypatch: pytest.MonkeyPatch, fake_marker: Path) -> None:
    """Fresh installs hit 404 on both names; that's a clean no-op, not an error."""
    _patch_ready(monkeypatch)

    def factory(*args: Any, **kwargs: Any) -> _StubClient:
        return _StubClient(delete_status={"loki": 404, "tempo": 404})

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
        return _StubClient(delete_status={"loki": 200, "tempo": 404})

    monkeypatch.setattr(grafana_cleanup.httpx, "Client", factory)
    deleted = cleanup_orphaned_grafana_datasources(marker_path=fake_marker)
    assert deleted == 1
    assert fake_marker.exists()
