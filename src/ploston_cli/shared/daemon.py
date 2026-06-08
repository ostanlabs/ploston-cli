"""Shared daemon scaffolding for ploston-cli background processes.

Provides a small ``DaemonSpec`` abstraction so the runner and the inspector
share the same double-fork/PID/signal/health-probe pipeline. Each daemon
module supplies its own ``DaemonSpec`` and a ``run_func``; everything else
(start/stop/status, stale-PID recovery, optional readiness probe) is shared.
"""

import contextlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
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
    # Optional identity hint used to guard against PID recycling. When set,
    # ``is_running`` (and therefore ``stop_daemon``) only treats a live PID as
    # this daemon if the process cmdline contains this token. This prevents
    # signalling an unrelated process that happens to have reused the PID after
    # the daemon died without cleaning up its PID file. ``None`` (the default)
    # preserves the historical behaviour (trust the PID unconditionally).
    identity_token: str | None = None


def _read_process_cmdline(pid: int) -> str | None:
    """Return the command line of *pid*, or ``None`` if it can't be read.

    Cross-platform, degrades gracefully:
    1. ``psutil`` if installed (works on macOS + Linux + Windows).
    2. ``/proc/<pid>/cmdline`` on Linux.
    3. ``ps -p <pid> -o command=`` (macOS + most Unixes) as a last resort.

    Returns ``None`` when no method can determine the cmdline, so callers can
    decide to degrade to a plain liveness check rather than misclassify.
    """
    # 1. psutil (optional dependency)
    try:
        import psutil  # type: ignore

        try:
            return " ".join(psutil.Process(pid).cmdline())
        except Exception:
            return None
    except ImportError:
        pass

    # 2. Linux procfs
    proc_path = Path(f"/proc/{pid}/cmdline")
    if proc_path.exists():
        try:
            raw = proc_path.read_bytes()
            return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
        except OSError:
            return None

    # 3. ps fallback (macOS + Unix)
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            line = result.stdout.strip()
            return line or None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def _pid_matches_identity(pid: int, spec: DaemonSpec) -> bool:
    """Return True if *pid* looks like the *spec* daemon (or can't be checked).

    A live PID is accepted when:
    - the spec declares no ``identity_token`` (legacy behaviour), or
    - the cmdline can't be read at all (degrade gracefully — trust the PID), or
    - the cmdline contains the ``identity_token``.

    It is rejected only when the cmdline *is* readable and does *not* contain
    the token — i.e. the PID was recycled by an unrelated process.
    """
    token = spec.identity_token
    if not token:
        return True
    cmdline = _read_process_cmdline(pid)
    if cmdline is None:
        # Can't determine identity — don't risk a false negative.
        return True
    return token in cmdline


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
    except ProcessLookupError:
        spec.pid_file.unlink(missing_ok=True)
        return False, None
    except PermissionError:
        # Process exists but is owned by another user — we can't inspect its
        # cmdline reliably, so trust the PID (historical behaviour).
        return True, pid

    # The PID is alive. Guard against PID recycling: only treat it as the
    # daemon when its identity matches (when an identity_token is configured).
    if not _pid_matches_identity(pid, spec):
        spec.pid_file.unlink(missing_ok=True)
        return False, None
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


@contextlib.contextmanager
def _start_lock(spec: DaemonSpec) -> Iterator[None]:
    """Hold an exclusive, OS-level lock around the start critical section.

    Prevents a double-start race where two concurrent ``ploston <name> start``
    invocations both pass the ``is_running`` check and both fork a daemon.
    Uses ``fcntl.flock`` on POSIX; on platforms without ``fcntl`` (e.g.
    Windows) it degrades to a no-op lock (best-effort) so the CLI still works.

    Raises ``BlockingIOError`` if the lock is already held by another process.
    """
    lock_path = spec.pid_file.with_suffix(spec.pid_file.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import fcntl
    except ImportError:
        # No file locking available — degrade to no-op.
        yield
        return

    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def start_daemon(
    spec: DaemonSpec,
    run_func: Callable[..., Any],
    *,
    on_ready: Callable[[], None] | None = None,
    **kwargs: Any,
) -> None:
    """Fork-detach ``run_func`` as a daemon described by ``spec``.

    Uses double-fork to fully detach from the terminal. The parent waits for
    the grandchild to write its PID file, then (if configured) waits for
    ``spec.health_probe`` to return True. On health-probe failure the parent
    prints a tail of the log and exits non-zero.

    ``on_ready`` fires in the parent process after the daemon is confirmed
    healthy but before the parent ``sys.exit(0)``s. Use this for side-effects
    like opening a browser that must happen after the daemon is ready but
    cannot happen in the grandchild.
    """
    # Serialize the is_running check + spawn so two concurrent starts can't
    # both pass the check and both fork a daemon (double-start race).
    try:
        lock_cm = _start_lock(spec)
        lock_cm.__enter__()
    except BlockingIOError:
        print(
            f"{spec.name.capitalize()} start already in progress "
            f"(another process holds the start lock)."
        )
        sys.exit(1)

    pid = -1  # sentinel so the finally never sees an unbound name
    in_child = False  # True only in the forked child (which released its own fd)
    try:
        alive, pid = is_running(spec)
        if alive:
            print(
                f"{spec.name.capitalize()} already running (PID {pid}). "
                f"Use 'ploston {spec.name} stop' first."
            )
            sys.exit(1)

        spec.pid_file.parent.mkdir(parents=True, exist_ok=True)

        pid = os.fork()
        if pid == 0:
            # Child / grandchild path: release the parent's start lock fd so it
            # is not retained for the daemon's whole lifetime, then proceed.
            in_child = True
            try:
                lock_cm.__exit__(None, None, None)
            except Exception:
                pass
    finally:
        # Release the lock in the parent (and on any error before the fork).
        # The child already released its inherited fd above; releasing again
        # would double-close, so skip it there.
        if not in_child:
            try:
                lock_cm.__exit__(None, None, None)
            except Exception:
                pass

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
        if on_ready is not None:
            on_ready()
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
