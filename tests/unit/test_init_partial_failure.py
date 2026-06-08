"""Phase-3 robustness test: init --import injection partial-failure exit code.

When one or more injection targets fail, ``init --import --inject`` must exit
non-zero (previously it printed a warning but exited 0, masking the failure).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ploston_cli.commands import init as init_mod


@dataclass
class FakeServerInfo:
    command: str = "npx"
    args: list = field(default_factory=list)
    transport: str = "stdio"
    env: dict = field(default_factory=dict)


@dataclass
class FakeDetected:
    source: str
    path: Path | None
    found: bool = True


def _patched_complete_flow(tmp_path, injection_results):
    """Run _complete_import_flow with all external effects mocked.

    Returns the SystemExit raised (or None).
    """
    servers = {"github": FakeServerInfo()}

    mock_client = AsyncMock()
    mock_client.push_runner_config = AsyncMock(return_value=None)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    fake_secret_detector = MagicMock()
    fake_secret_detector.detect.return_value = False

    runner_starter = MagicMock()
    runner_starter.check_runner_status.return_value = (False, "")
    runner_starter.start_runner.return_value = (True, "")

    with (
        patch.object(init_mod, "PlostClient", return_value=mock_client),
        patch.object(init_mod, "write_env_file", return_value=tmp_path / ".env"),
        patch.object(init_mod, "load_env_file", return_value={}),
        patch.object(init_mod, "generate_runner_token", return_value="ploston_runner_x"),
        patch.object(init_mod, "select_targets", return_value=["cursor"]),
        patch.object(init_mod, "run_injection", return_value=injection_results),
        patch("ploston_core.config.secrets.SecretDetector", return_value=fake_secret_detector),
        patch("ploston_cli.bootstrap.RunnerAutoStart", return_value=runner_starter),
    ):
        import asyncio

        detected = [FakeDetected(source="cursor", path=tmp_path / "cursor.json")]
        try:
            asyncio.run(
                init_mod._complete_import_flow(
                    cp_url="http://localhost:8022",
                    detected_configs=detected,
                    servers=servers,
                    selected_names=["github"],
                    runner_name=None,
                    inject=True,
                    inject_targets=["cursor"],
                    non_interactive=True,
                )
            )
        except SystemExit as exc:
            return exc
        return None


@pytest.mark.cli_unit
def test_injection_failure_exits_nonzero(tmp_path):
    # One target failed during injection.
    results = [("cursor", tmp_path / "cursor.json", "permission denied")]
    exc = _patched_complete_flow(tmp_path, results)
    assert exc is not None, "expected SystemExit on injection failure"
    assert exc.code == 1


@pytest.mark.cli_unit
def test_injection_success_does_not_exit_nonzero(tmp_path):
    # All targets succeeded — no error → no non-zero exit.
    results = [("cursor", tmp_path / "cursor.json", None)]
    exc = _patched_complete_flow(tmp_path, results)
    assert exc is None or exc.code in (0, None)
