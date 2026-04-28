"""Daemon management for the runner.

Thin wrapper around :mod:`ploston_cli.shared.daemon`. Preserves the
existing public API (``is_running``, ``start_daemon``, ``stop_daemon``,
``get_pid``) so existing callers (CLI commands, bootstrap teardown) are
unaffected by the underlying refactor.
"""

from collections.abc import Callable
from typing import Any

from ..shared import daemon as _daemon
from ..shared.paths import LOG_DIR, RUNNER_PID_FILE

LOG_FILE = LOG_DIR / "runner.log"

_SPEC = _daemon.DaemonSpec(
    name="runner",
    pid_file=RUNNER_PID_FILE,
    log_file=LOG_FILE,
)


def is_running() -> tuple[bool, int | None]:
    """Check if the runner daemon is alive."""
    return _daemon.is_running(_SPEC)


def get_pid() -> int | None:
    """Return the runner daemon's PID, or ``None`` if not running."""
    return _daemon.get_pid(_SPEC)


def start_daemon(run_func: Callable[..., Any], **kwargs: Any) -> None:
    """Fork-detach ``run_func`` as the runner daemon.

    Pops ``log_level`` from ``kwargs`` and configures JSON logging to
    ``LOG_FILE`` in the grandchild before invoking ``run_func``.
    """
    log_level = kwargs.pop("log_level", "info")

    def _wrapped(**inner_kwargs: Any) -> None:
        from ..shared.logging import configure_logging

        configure_logging(level=log_level, log_file=LOG_FILE, json_output=True)
        run_func(**inner_kwargs)

    _daemon.start_daemon(_SPEC, _wrapped, **kwargs)


def stop_daemon() -> None:
    """Stop the runner daemon via SIGTERM (5s grace, then SIGKILL)."""
    _daemon.stop_daemon(_SPEC)
