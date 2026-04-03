"""Tests for dynamic shell completions (T-767).

See: DEC169-175_ROUTING_TAGS_CLI_SPEC.md §5
"""

from __future__ import annotations

import json

import click

from ploston_cli.completion import (
    PlostCompletionSource,
    complete_workflow_names,
    write_completions_cache,
)


class TestPlostCompletionSource:
    """Tests for PlostCompletionSource."""

    def test_missing_cache_returns_empty(self, tmp_path):
        """Missing cache file returns empty lists."""
        src = PlostCompletionSource(cache_path=tmp_path / "nope.json")
        assert src.workflows() == []
        assert src.runners() == []
        assert src.servers() == []
        assert src.tags() == []

    def test_corrupt_cache_returns_empty(self, tmp_path):
        """Corrupt JSON returns empty list without raising."""
        bad = tmp_path / "bad.json"
        bad.write_text("NOT JSON!!!")
        src = PlostCompletionSource(cache_path=bad)
        assert src.workflows() == []

    def test_reads_workflows(self, tmp_path):
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps({"workflows": ["alpha", "beta"]}))
        src = PlostCompletionSource(cache_path=cache)
        assert src.workflows() == ["alpha", "beta"]

    def test_reads_runners(self, tmp_path):
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps({"runners": ["mac-mini"]}))
        src = PlostCompletionSource(cache_path=cache)
        assert src.runners() == ["mac-mini"]

    def test_reads_servers(self, tmp_path):
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps({"servers": ["github", "filesystem"]}))
        src = PlostCompletionSource(cache_path=cache)
        assert src.servers() == ["github", "filesystem"]

    def test_reads_tags(self, tmp_path):
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps({"tags": ["kind:workflow", "server:github"]}))
        src = PlostCompletionSource(cache_path=cache)
        assert src.tags() == ["kind:workflow", "server:github"]


class TestWriteCompletionsCache:
    """Tests for write_completions_cache."""

    def test_creates_cache_file(self, tmp_path):
        path = tmp_path / "sub" / "cache.json"
        write_completions_cache(workflows=["foo"], cache_path=path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["workflows"] == ["foo"]
        assert "updated_at" in data

    def test_merge_preserves_existing_keys(self, tmp_path):
        path = tmp_path / "cache.json"
        path.write_text(json.dumps({"workflows": ["old"], "runners": ["mac"]}))
        write_completions_cache(workflows=["new"], cache_path=path)
        data = json.loads(path.read_text())
        assert data["workflows"] == ["new"]
        assert data["runners"] == ["mac"]  # preserved

    def test_deduplicates_and_sorts(self, tmp_path):
        path = tmp_path / "cache.json"
        write_completions_cache(workflows=["beta", "alpha", "beta"], cache_path=path)
        data = json.loads(path.read_text())
        assert data["workflows"] == ["alpha", "beta"]


class TestCompleteCallbacks:
    """Tests for Click completion callbacks."""

    def test_complete_workflow_names_filters_by_prefix(self, tmp_path, monkeypatch):
        """complete_workflow_names returns only names starting with prefix."""
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps({"workflows": ["diagnose_ci", "deploy_app", "check_health"]}))
        # Patch the module-level _source
        from ploston_cli import completion

        monkeypatch.setattr(completion, "_source", PlostCompletionSource(cache_path=cache))

        ctx = click.Context(click.Command("test"))
        items = complete_workflow_names(ctx, click.Argument(["name"]), "diag")
        names = [i.value for i in items]
        assert names == ["diagnose_ci"]

    def test_complete_workflow_names_empty_prefix_returns_all(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps({"workflows": ["a", "b"]}))
        from ploston_cli import completion

        monkeypatch.setattr(completion, "_source", PlostCompletionSource(cache_path=cache))

        ctx = click.Context(click.Command("test"))
        items = complete_workflow_names(ctx, click.Argument(["name"]), "")
        assert len(items) == 2
