"""FB-1 data-loss regression tests (Claude Desktop config wipe + lost backup).

These tests assert the CORRECT behaviour. They are written TEST-FIRST and are
expected to be RED against the pre-fix code, demonstrating the two compounding
defects:

  Defect A (wipe): re-injecting with an empty server list collapses the config
                   down to just the fixed ploston/ploston-authoring bridges,
                   wiping the user's real servers and unrelated top-level keys.
  Defect B (rollback impossible): the single Layer-2 backup is frozen at first
                   touch (stale), and make_backup happily canonicalises an
                   already-injected config, so rollback can never restore the
                   user's original servers.

Reference: documentation/REMAINING_ISSUES_PLAN.md "Investigations / FB-1".
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ploston_cli.init.backup import (
    find_latest_backup,
    is_backup_file,
    make_backup,
    restore_from_backup,
)
from ploston_cli.init.injector import (
    _is_ploston_bridge_entry,
    inject_ploston_into_config,
    is_already_injected,
    restore_config_from_imported,
)

MOCK_PLOSTON_PATH = "/usr/local/bin/ploston"


@pytest.fixture(autouse=True)
def _mock_ploston_which():
    """Mock shutil.which('ploston') so bridge entries are deterministic."""
    with patch("ploston_cli.init.injector.shutil.which", return_value=MOCK_PLOSTON_PATH):
        yield


def _server(name: str) -> dict:
    return {"command": "npx", "args": [f"@mcp/{name}"]}


def _write_config(path, servers: dict, extra: dict | None = None) -> None:
    config: dict = {"mcpServers": dict(servers)}
    if extra:
        config.update(extra)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _bridge_entries(mcp_servers: dict) -> set[str]:
    return {name for name, entry in mcp_servers.items() if _is_ploston_bridge_entry(entry)}


def _recoverable_user_servers(config_path) -> set[str]:
    """All user-server names recoverable from the on-disk config.

    Combines: live non-bridge mcpServers entries + the _ploston_imported
    backup section (excluding metadata keys). This is the set a correct
    rollback can restore.
    """
    config = json.loads(config_path.read_text(encoding="utf-8"))
    mcp = config.get("mcpServers", {})
    live_user = {n for n, e in mcp.items() if not _is_ploston_bridge_entry(e)}
    imported = config.get("_ploston_imported", {}) or {}
    backed_up = {
        ("ploston" if k == "ploston-original" else k) for k in imported if not k.startswith("_")
    }
    return live_user | backed_up


# ---------------------------------------------------------------------------
# (a) Re-inject with [] must not wipe user servers / unrelated keys, and
#     rollback must restore the original servers with no bridge entries.
# ---------------------------------------------------------------------------
class TestEmptyReinjectDoesNotWipe:
    def test_user_servers_and_unrelated_keys_survive_empty_reinject(self, tmp_path):
        config_file = tmp_path / "claude_desktop_config.json"
        _write_config(
            config_file,
            {"S1": _server("s1"), "S2": _server("s2")},
            extra={"globalShortcut": "Cmd+Shift+Space"},
        )

        # First inject: file-sourced S1, S2.
        inject_ploston_into_config(
            config_path=config_file,
            imported_servers=["S1", "S2"],
            cp_url="http://localhost:8022",
        )

        # Re-inject with [] (simulates CP returning no non-bridge servers).
        # This must NOT collapse the config. Either a no-op or a raise is
        # acceptable, but the user's data must survive either way.
        try:
            inject_ploston_into_config(
                config_path=config_file,
                imported_servers=[],
                cp_url="http://localhost:8022",
            )
        except Exception:
            # An abort/raise is an acceptable correct behaviour (merge invariant).
            pass

        # User servers still recoverable.
        assert {"S1", "S2"}.issubset(_recoverable_user_servers(config_file))

        # Unrelated top-level key survived.
        config = json.loads(config_file.read_text(encoding="utf-8"))
        assert config.get("globalShortcut") == "Cmd+Shift+Space"

    def test_rollback_restores_user_servers_without_bridges(self, tmp_path):
        config_file = tmp_path / "claude_desktop_config.json"
        _write_config(
            config_file,
            {"S1": _server("s1"), "S2": _server("s2")},
            extra={"globalShortcut": "Cmd+Shift+Space"},
        )

        inject_ploston_into_config(
            config_path=config_file,
            imported_servers=["S1", "S2"],
            cp_url="http://localhost:8022",
        )
        try:
            inject_ploston_into_config(
                config_path=config_file,
                imported_servers=[],
                cp_url="http://localhost:8022",
            )
        except Exception:
            pass

        # Inline rollback.
        restore_config_from_imported(config_file)
        config = json.loads(config_file.read_text(encoding="utf-8"))
        mcp = config.get("mcpServers", {})

        assert "S1" in mcp
        assert "S2" in mcp
        assert _bridge_entries(mcp) == set(), f"bridge entries leaked: {_bridge_entries(mcp)}"
        assert config.get("globalShortcut") == "Cmd+Shift+Space"

    def test_layer2_rollback_restores_user_servers_without_bridges(self, tmp_path):
        config_file = tmp_path / "claude_desktop_config.json"
        _write_config(
            config_file,
            {"S1": _server("s1"), "S2": _server("s2")},
            extra={"globalShortcut": "Cmd+Shift+Space"},
        )

        inject_ploston_into_config(
            config_path=config_file,
            imported_servers=["S1", "S2"],
            cp_url="http://localhost:8022",
        )
        try:
            inject_ploston_into_config(
                config_path=config_file,
                imported_servers=[],
                cp_url="http://localhost:8022",
            )
        except Exception:
            pass

        # Layer-2 file rollback must land on a known-good (non-injected) backup.
        assert restore_from_backup(config_file) is True
        config = json.loads(config_file.read_text(encoding="utf-8"))
        mcp = config.get("mcpServers", {})
        assert "S1" in mcp
        assert "S2" in mcp
        assert _bridge_entries(mcp) == set()
        assert config.get("globalShortcut") == "Cmd+Shift+Space"


# ---------------------------------------------------------------------------
# (b) Backups must refresh, not freeze at first touch.
# ---------------------------------------------------------------------------
class TestBackupsRefresh:
    def test_latest_backup_captures_post_first_touch_user_changes(self, tmp_path):
        config_file = tmp_path / "claude_desktop_config.json"
        _write_config(config_file, {"S1": _server("s1")})

        # First inject of S1 (creates the first Layer-2 backup of {S1}).
        inject_ploston_into_config(
            config_path=config_file,
            imported_servers=["S1"],
            cp_url="http://localhost:8022",
        )

        # User then rolls back and directly adds a brand-new server S2.
        restore_config_from_imported(config_file)
        _write_config(config_file, {"S1": _server("s1"), "S2": _server("s2")})

        # Re-inject. A fresh backup of the {S1,S2} state must be taken
        # *before* this modification.
        inject_ploston_into_config(
            config_path=config_file,
            imported_servers=["S1", "S2"],
            cp_url="http://localhost:8022",
        )

        latest = find_latest_backup(config_file)
        assert latest is not None
        backup_config = json.loads(latest.read_text(encoding="utf-8"))
        backup_mcp = backup_config.get("mcpServers", {})
        # The LATEST known-good backup must contain S2 (proves backups refresh).
        assert "S2" in backup_mcp, (
            f"latest backup is frozen at first-touch and lost S2: {sorted(backup_mcp)}"
        )
        # And it must be a clean (non-injected) snapshot.
        assert _bridge_entries(backup_mcp) == set()


# ---------------------------------------------------------------------------
# (c) An already-injected config must never be the canonical restore point.
# ---------------------------------------------------------------------------
class TestNoInjectedCanonicalBackup:
    def test_make_backup_of_injected_config_is_not_canonical(self, tmp_path):
        config_file = tmp_path / "claude_desktop_config.json"
        _write_config(config_file, {"S1": _server("s1"), "S2": _server("s2")})

        # Inject (this takes a clean backup of {S1,S2}).
        inject_ploston_into_config(
            config_path=config_file,
            imported_servers=["S1", "S2"],
            cp_url="http://localhost:8022",
        )
        assert is_already_injected(config_file)

        # Now explicitly ask for a backup of the already-injected config.
        make_backup(config_file)

        # The canonical restore point (find_latest_backup) must NOT be a
        # bridged/injected config.
        latest = find_latest_backup(config_file)
        assert latest is not None
        backup_config = json.loads(latest.read_text(encoding="utf-8"))
        backup_mcp = backup_config.get("mcpServers", {})
        assert _bridge_entries(backup_mcp) == set(), (
            "canonical backup is an injected config — rollback would restore "
            f"a bridged config: {sorted(backup_mcp)}"
        )
        assert {"S1", "S2"}.issubset(set(backup_mcp))

        # And restore_from_backup must land on the clean snapshot.
        assert restore_from_backup(config_file) is True
        restored = json.loads(config_file.read_text(encoding="utf-8"))
        assert _bridge_entries(restored.get("mcpServers", {})) == set()

    def test_newest_backup_that_is_injected_is_excluded_from_canonical(self, tmp_path):
        """Even if an injected snapshot is the newest backup on disk, it must
        not be selected as the canonical restore point.

        Pre-fix, find_latest_backup picks the lexicographically-newest file
        matching the timestamp pattern regardless of contents, so a backup of
        an injected config would be restored — re-bridging the user's config.
        """
        config_file = tmp_path / "claude_desktop_config.json"
        _write_config(config_file, {"S1": _server("s1"), "S2": _server("s2")})

        # An OLD clean (known-good) backup.
        clean = config_file.parent / f"{config_file.name}.ploston-backup-2025-01-01T00-00-00Z"
        clean.write_text(
            json.dumps({"mcpServers": {"S1": _server("s1"), "S2": _server("s2")}}),
            encoding="utf-8",
        )

        # A NEWER backup that happens to contain an injected (bridged) config.
        injected_snapshot = {
            "mcpServers": {
                "ploston": {"command": "p", "args": ["bridge", "--tags", "kind:workflow"]},
                "ploston-authoring": {
                    "command": "p",
                    "args": ["bridge", "--tags", "kind:workflow_mgmt"],
                },
            }
        }
        newer_injected = (
            config_file.parent / f"{config_file.name}.ploston-backup-2099-01-01T00-00-00Z"
        )
        newer_injected.write_text(json.dumps(injected_snapshot), encoding="utf-8")

        latest = find_latest_backup(config_file)
        assert latest is not None
        backup_config = json.loads(latest.read_text(encoding="utf-8"))
        assert _bridge_entries(backup_config.get("mcpServers", {})) == set(), (
            f"find_latest_backup selected an injected snapshot as canonical: {latest.name}"
        )
        assert {"S1", "S2"}.issubset(set(backup_config.get("mcpServers", {})))


# ---------------------------------------------------------------------------
# (d) A malformed existing config must not be overwritten.
# ---------------------------------------------------------------------------
class TestMalformedConfigNotClobbered:
    def test_injection_aborts_and_preserves_malformed_file(self, tmp_path):
        config_file = tmp_path / "claude_desktop_config.json"
        malformed = '{"mcpServers": {"S1": {"command": "npx"  BROKEN'
        config_file.write_text(malformed, encoding="utf-8")

        with pytest.raises(Exception):
            inject_ploston_into_config(
                config_path=config_file,
                imported_servers=["S1"],
                cp_url="http://localhost:8022",
            )

        # The malformed file must be untouched (not overwritten / not wiped).
        assert config_file.read_text(encoding="utf-8") == malformed

        # And no injected (bridged) backup should have been left as canonical.
        latest = find_latest_backup(config_file)
        if latest is not None:
            assert is_backup_file(latest)
