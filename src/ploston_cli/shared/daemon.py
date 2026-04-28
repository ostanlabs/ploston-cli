"""Shared daemon scaffolding for ploston-cli background processes.

Provides a small ``DaemonSpec`` abstraction so the runner and the inspector
share the same double-fork/PID/signal/health-probe pipeline. Each daemon
module supplies its own ``DaemonSpec`` and a ``run_func``; everything else
(start/stop/status, stale-PID recovery, optional readiness probe) is shared.
"""

import os
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DaemonSpec:
    """Configuration for a single daemon's lifecycle."""

    name: str
    pid_file: Path
    log_file: Path
    # Optional readiness probe run in the *parent* after fork. When provided,
    # ``start_daemon`` polls this until True (or timeout) before reporting
    # success to the user. Useful for "waited for the port to bind".
    health_probe: Callable[[], bool] | None = None
    health_probe_timeout_s: float = 5.0
    health_probe_interval_s: float = 0.1


def is_running(spec: DaemonSpec) -> tuple[bool, int | None]:
    """Check whether ``spec`` daemon is alive. Cleans up stale PID files."""
    if not spec.pid_file.exists():
        return False, None
    try:
        pid = int(spec.pid_file.read_text().strip())
    except (ValueError, OSError):
        spec.pid_file.unlink(missing_ok=True)
        return False, None
    try:
        os.kill(pid, 0)
        return True, pid
    except ProcessLookupError:
        spec.pid_file.unlink(missing_ok=True)
        return False, None
    except PermissionError:
        return True, pid


def get_pid(spec: DaemonSpec) -> int | None:
    """Return the live daemon's PID, or ``None`` if not running."""
    alive, pid = is_running(spec)
    return pid if alive else None


def _tail_lines(path: Path, n: int = 20) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            chunk = min(size, 4096)
            f.seek(size - chunk)
            data = f.read(chunk).decode("utf-8", errors="replace")
        lines = data.splitlines()
        return "\n".join(lines[-n:])
    except (OSError, ValueError):
        return ""


def start_daemon(
    spec: DaemonSpec,
    run_func: Callable[..., Any],
    **kwargs: Any,
) -> None:
    """Fork-detach ``run_func`` as a daemon described by ``spec``.

    Uses double-fork to fully detach from the terminal. The parent waits for
    the grandchild to write its PID file, then (if configured) waits for
    ``spec.health_probe`` to return True. On health-probe failure the parent
    prints a tail of the log and exits non-zero.
    """
    alive, pid = is_running(spec)
    if alive:
        print(
            f"{spec.name.capitalize()} already running (PID {pid}). "
            f"Use 'ploston {spec.name} stop' first."
        )
        sys.exit(1)

    spec.pid_file.parent.mkdir(parents=True, exist_ok=True)

    pid = os.fork()
    if pid > 0:
        time.sleep(0.5)
        alive, child_pid = is_running(spec)
        if not alive:
            tail = _tail_lines(spec.log_file)
            print(f"{spec.name.capitalize()} failed to start. Check logs: {spec.log_file}")
            if tail:
                print("--- last log lines ---")
                print(tail)
            sys.exit(1)
        if spec.health_probe is not None:
            deadline = time.time() + spec.health_probe_timeout_s
            ready = False
            while time.time() < deadline:
                try:
                    if spec.health_probe():
                        ready = True
                        break
                except Exception:
                    pass
                time.sleep(spec.health_probe_interval_s)
            if not ready:
                tail = _tail_lines(spec.log_file)
                print(
                    f"{spec.name.capitalize()} started (PID {child_pid}) but did not "
                    f"become ready within {spec.health_probe_timeout_s:.0f}s."
                )
                if tail:
                    print("--- last log lines ---")
                    print(tail)
                sys.exit(1)
        print(f"{spec.name.capitalize()} started (PID {child_pid})")
        print(f"Logs: {spec.log_file}")
        sys.exit(0)

    os.setsid()
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    spec.pid_file.write_text(str(os.getpid()))
    log_fd = open(spec.log_file, "a")
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())

    pid_file = spec.pid_file

    def _on_signal(signum: int, frame: Any) -> None:
        pid_file.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    try:
        run_func(**kwargs)
    finally:
        spec.pid_file.unlink(missing_ok=True)


def stop_daemon(
    spec: DaemonSpec,
    on_stopped: Callable[[], None] | None = None,
) -> None:
    """Stop daemon via SIGTERM. Waits up to 5s, then force-kills.

    ``on_stopped`` runs only when the daemon is confirmed dead (graceful or
    force-killed). Used by callers that need to clean up sidecar files such
    as a token cache.
    """
    alive, pid = is_running(spec)
    if not alive:
        print(f"{spec.name.capitalize()} is not running.")
        return

    os.kill(pid, signal.SIGTERM)

    for _ in range(50):
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            spec.pid_file.unlink(missing_ok=True)
            print(f"{spec.name.capitalize()} stopped (was PID {pid}).")
            if on_stopped is not None:
                on_stopped()
            return

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    spec.pid_file.unlink(missing_ok=True)
    print(f"{spec.name.capitalize()} force-killed (PID {pid}).")
    if on_stopped is not None:
        on_stopped()
