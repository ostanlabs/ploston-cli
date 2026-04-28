"""Daemon management for the inspector.

Thin wrapper around :mod:`ploston_cli.shared.daemon` configured with the
inspector's PID/log paths and a ``/healthz`` readiness probe so the parent
``ploston inspector start --daemon`` invocation can wait for the UI port to
bind before reporting success to the user.

Maintains a JSON sidecar (``INSPECTOR_STATE_FILE``) recording the bound
``host``/``port`` so ``ploston inspector status`` and ``ploston bootstrap
status`` can surface the listening URL without re-deriving it from defaults.
"""

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from ..shared import daemon as _daemon
from ..shared.paths import INSPECTOR_LOG_FILE, INSPECTOR_PID_FILE, INSPECTOR_STATE_FILE


def _make_health_probe(host: str, port: int) -> Callable[[], bool]:
    """Build a parent-side readiness probe targeting ``GET /healthz``.

    Uses ``urllib`` from the standard library so the parent process does not
    have to import the async HTTP stack.
    """
    url = f"http://{host}:{port}/healthz"

    def _probe() -> bool:
        try:
            with urlopen(url, timeout=0.5) as resp:
                return 200 <= resp.status < 300
        except (URLError, OSError, ValueError):
            return False

    return _probe


def _build_spec(host: str, port: int) -> _daemon.DaemonSpec:
    return _daemon.DaemonSpec(
        name="inspector",
        pid_file=INSPECTOR_PID_FILE,
        log_file=INSPECTOR_LOG_FILE,
        health_probe=_make_health_probe(host, port),
        health_probe_timeout_s=10.0,
    )


# A spec without a health probe is sufficient for ``is_running`` /
# ``stop_daemon`` because those only consult the PID file. Having a singleton
# avoids requiring callers to pass host/port for read-only operations.
_DEFAULT_SPEC = _daemon.DaemonSpec(
    name="inspector",
    pid_file=INSPECTOR_PID_FILE,
    log_file=INSPECTOR_LOG_FILE,
)


def is_running() -> tuple[bool, int | None]:
    """Check if the inspector daemon is alive."""
    return _daemon.is_running(_DEFAULT_SPEC)


def get_pid() -> int | None:
    """Return the inspector daemon's PID, or ``None`` if not running."""
    return _daemon.get_pid(_DEFAULT_SPEC)


def _write_state(host: str, port: int, url: str | None) -> None:
    """Persist the inspector's bound listener and CP URL.

    Written by the grandchild after ``run_func`` is invoked. Best-effort —
    failure to persist must never crash the daemon (status display degrades
    gracefully when the file is missing).

    ``host`` records the literal value the user passed (default
    ``"127.0.0.1"``); ``bind_hosts`` is the authoritative list of addresses
    the server is actually listening on (loopback expands to both stacks).
    """
    from .server import resolve_bind_hosts

    payload = {
        "host": host,
        "port": port,
        "bind_hosts": resolve_bind_hosts(host),
        "url": url,
        "started_at": time.time(),
    }
    try:
        INSPECTOR_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        INSPECTOR_STATE_FILE.write_text(json.dumps(payload))
    except OSError:
        pass


def _clear_state() -> None:
    INSPECTOR_STATE_FILE.unlink(missing_ok=True)


def read_state() -> dict[str, Any] | None:
    """Return the daemon's recorded ``host``/``port``/``url``, or ``None``.

    Callers (status commands) use this to surface the listening URL. Returns
    ``None`` if the daemon is not running, the state file is missing, or the
    payload is corrupt — never raises.
    """
    alive, _ = is_running()
    if not alive:
        return None
    if not INSPECTOR_STATE_FILE.exists():
        return None
    try:
        return json.loads(INSPECTOR_STATE_FILE.read_text())
    except (OSError, ValueError):
        return None


def start_daemon(
    run_func: Callable[..., Any],
    *,
    host: str,
    port: int,
    **kwargs: Any,
) -> None:
    """Fork-detach ``run_func`` as the inspector daemon.

    ``host`` and ``port`` serve double duty: they parameterise the parent-side
    health probe (via the daemon spec) *and* are forwarded to ``run_func`` so
    the daemon-side ``run_inspector_daemon`` can bind the same address.

    Wraps ``run_func`` so the grandchild persists ``INSPECTOR_STATE_FILE`` for
    status display and clears it on exit.
    """
    spec = _build_spec(host, port)

    def _run_with_state(**inner: Any) -> None:
        _write_state(
            host=inner.get("host", host),
            port=inner.get("port", port),
            url=inner.get("url"),
        )
        try:
            run_func(**inner)
        finally:
            _clear_state()

    _daemon.start_daemon(spec, _run_with_state, host=host, port=port, **kwargs)


def stop_daemon(on_stopped: Callable[[], None] | None = None) -> None:
    """Stop the inspector daemon via SIGTERM (5s grace, then SIGKILL).

    Clears ``INSPECTOR_STATE_FILE`` after the daemon is confirmed dead. The
    grandchild's ``finally`` block also clears it; this second pass handles
    the SIGKILL path where Python finalisers do not run.
    """

    def _composed_on_stopped() -> None:
        _clear_state()
        if on_stopped is not None:
            on_stopped()

    _daemon.stop_daemon(_DEFAULT_SPEC, on_stopped=_composed_on_stopped)
