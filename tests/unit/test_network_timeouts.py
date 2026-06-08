"""Phase-3 robustness tests: bounded timeouts on bootstrap docker calls.

Non-``up`` docker calls (network inspect / rm / suggest-name probes) must pass
a ``timeout=`` so a hung docker daemon cannot wedge the bootstrap CLI forever.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ploston_cli.bootstrap.network import NetworkManager


@pytest.mark.cli_unit
def test_check_network_exists_passes_timeout():
    mgr = NetworkManager("ploston-network")
    with patch("ploston_cli.bootstrap.network.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        mgr.check_network_exists()
    assert mock_run.called
    assert mock_run.call_args.kwargs.get("timeout") is not None


@pytest.mark.cli_unit
def test_remove_network_passes_timeout():
    mgr = NetworkManager("ploston-network")
    with patch("ploston_cli.bootstrap.network.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mgr.remove_network()
    # The `docker network rm` call must carry a timeout.
    rm_calls = [c for c in mock_run.call_args_list if "rm" in c.args[0]]
    assert rm_calls, "expected a docker network rm call"
    assert rm_calls[0].kwargs.get("timeout") is not None


@pytest.mark.cli_unit
def test_suggest_alternative_name_passes_timeout():
    mgr = NetworkManager("ploston-network")
    with patch("ploston_cli.bootstrap.network.subprocess.run") as mock_run:
        # returncode != 0 → candidate is free, returns on first probe.
        mock_run.return_value = MagicMock(returncode=1)
        mgr.suggest_alternative_name()
    assert mock_run.called
    for call in mock_run.call_args_list:
        assert call.kwargs.get("timeout") is not None
