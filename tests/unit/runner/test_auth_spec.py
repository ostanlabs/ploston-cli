"""Specification tests for ploston_cli.runner.auth.TokenStorage.

Asserts the intended contract: token persistence round-trips, per-CP-URL
isolation, secure file permissions (0600), graceful handling of missing /
corrupt files, default path resolution (XDG vs ~/.config), and clearing.

Filesystem is the external boundary; we use real temp files (tmp_path) rather
than mocking, but never touch the user's real config dir.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from ploston_cli.runner.auth import TokenStorage, get_default_token_path

CP = "http://cp.example:8022"
CP2 = "http://other.example:8022"


# ---------------------------------------------------------------------------
# Default path resolution
# ---------------------------------------------------------------------------


def test_default_path_uses_xdg_config_home_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = get_default_token_path()
    assert path == tmp_path / "ploston" / "runner_token.json"


def test_default_path_falls_back_to_home_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    path = get_default_token_path()
    assert path == tmp_path / ".config" / "ploston" / "runner_token.json"


# ---------------------------------------------------------------------------
# load() contract
# ---------------------------------------------------------------------------


def test_load_returns_false_when_file_missing(tmp_path):
    storage = TokenStorage(token_path=tmp_path / "nope.json")
    assert storage.load() is False


def test_load_returns_true_and_populates_data_for_valid_file(tmp_path):
    p = tmp_path / "runner_token.json"
    p.write_text(json.dumps({CP: {"token": "abc", "runner_id": "r1"}}))
    storage = TokenStorage(token_path=p)
    assert storage.load() is True
    assert storage.get_token(CP) == "abc"
    assert storage.get_runner_id(CP) == "r1"


def test_load_returns_false_on_corrupt_json(tmp_path):
    """A malformed token file must be handled gracefully (return False)."""
    p = tmp_path / "runner_token.json"
    p.write_text("{ not valid json ")
    storage = TokenStorage(token_path=p)
    assert storage.load() is False


# ---------------------------------------------------------------------------
# save() contract — persistence & permissions
# ---------------------------------------------------------------------------


def test_save_creates_parent_dirs_and_round_trips(tmp_path):
    p = tmp_path / "nested" / "dir" / "runner_token.json"
    storage = TokenStorage(token_path=p)
    storage.set_token(CP, "tok", runner_id="rid")
    assert storage.save() is True
    assert p.exists()

    reloaded = TokenStorage(token_path=p)
    assert reloaded.load() is True
    assert reloaded.get_token(CP) == "tok"
    assert reloaded.get_runner_id(CP) == "rid"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics")
def test_save_sets_owner_only_permissions(tmp_path):
    """Token file must be written with 0600 (owner read/write only)."""
    p = tmp_path / "runner_token.json"
    storage = TokenStorage(token_path=p)
    storage.set_token(CP, "tok")
    storage.save()
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


# ---------------------------------------------------------------------------
# get/set/clear semantics
# ---------------------------------------------------------------------------


def test_get_token_returns_none_for_unknown_url(tmp_path):
    storage = TokenStorage(token_path=tmp_path / "t.json")
    assert storage.get_token("http://unknown") is None
    assert storage.get_runner_id("http://unknown") is None


def test_set_token_isolated_per_cp_url(tmp_path):
    storage = TokenStorage(token_path=tmp_path / "t.json")
    storage.set_token(CP, "tok1", runner_id="r1")
    storage.set_token(CP2, "tok2", runner_id="r2")
    assert storage.get_token(CP) == "tok1"
    assert storage.get_token(CP2) == "tok2"
    assert storage.get_runner_id(CP2) == "r2"


def test_set_token_without_runner_id_stores_none(tmp_path):
    storage = TokenStorage(token_path=tmp_path / "t.json")
    storage.set_token(CP, "tok")
    assert storage.get_token(CP) == "tok"
    assert storage.get_runner_id(CP) is None


def test_clear_token_removes_only_target_url(tmp_path):
    storage = TokenStorage(token_path=tmp_path / "t.json")
    storage.set_token(CP, "tok1")
    storage.set_token(CP2, "tok2")
    storage.clear_token(CP)
    assert storage.get_token(CP) is None
    assert storage.get_token(CP2) == "tok2"


def test_clear_token_is_noop_for_unknown_url(tmp_path):
    storage = TokenStorage(token_path=tmp_path / "t.json")
    storage.set_token(CP, "tok")
    storage.clear_token("http://unknown")  # must not raise
    assert storage.get_token(CP) == "tok"


def test_clear_all_removes_everything(tmp_path):
    storage = TokenStorage(token_path=tmp_path / "t.json")
    storage.set_token(CP, "tok1")
    storage.set_token(CP2, "tok2")
    storage.clear_all()
    assert storage.get_token(CP) is None
    assert storage.get_token(CP2) is None


# ---------------------------------------------------------------------------
# delete_file() contract
# ---------------------------------------------------------------------------


def test_delete_file_removes_existing_file(tmp_path):
    p = tmp_path / "t.json"
    storage = TokenStorage(token_path=p)
    storage.set_token(CP, "tok")
    storage.save()
    assert p.exists()
    assert storage.delete_file() is True
    assert not p.exists()


def test_delete_file_returns_true_when_absent(tmp_path):
    """delete_file must succeed (True) when there is nothing to delete."""
    storage = TokenStorage(token_path=tmp_path / "missing.json")
    assert storage.delete_file() is True


def test_token_path_property_exposes_configured_path(tmp_path):
    p = tmp_path / "custom.json"
    assert TokenStorage(token_path=p).token_path == p
