"""H-9: the dead HeartbeatManager must be removed.

The HeartbeatManager class was exported but never instantiated; half-open
detection is covered by the websockets library's built-in ping/pong. The dead
code (and its module) is removed; runner exports must no longer expose it.
"""

import pytest


@pytest.mark.runner_unit
def test_heartbeat_module_removed() -> None:
    with pytest.raises(ImportError):
        import ploston_cli.runner.heartbeat  # noqa: F401


@pytest.mark.runner_unit
def test_heartbeat_manager_not_exported() -> None:
    import ploston_cli.runner as runner_pkg

    assert not hasattr(runner_pkg, "HeartbeatManager")
    assert "HeartbeatManager" not in runner_pkg.__all__
    assert "HeartbeatTimeoutError" not in runner_pkg.__all__
