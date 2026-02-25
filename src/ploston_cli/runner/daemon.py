"""Daemon management for the runner.

Handles:
- Fork process for daemon mode
- PID file management
- Signal handling for graceful shutdown
- Process lifecycle management
"""

import os
import signal
import sys
import time
from collections.abc import Callable
from typing import Any

from ..shared.paths import LOG_DIR, PID_FILE, PLOSTON_DIR

LOG_FILE = LOG_DIR / "runner.log"


def is_running() -> tuple[bool, int | None]:
    """Check if daemon is running.

    Returns:
        Tuple of (alive, pid). If not running, pid is None.
    """
    if not PID_FILE.exists():
        return False, None

    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        # Invalid PID file
        PID_FILE.unlink(missing_ok=True)
        return False, None

    try:
        os.kill(pid, 0)  # Signal 0 = check existence
        return True, pid
    except ProcessLookupError:
        # Stale PID file
        PID_FILE.unlink(missing_ok=True)
        return False, None
    except PermissionError:
        # Process exists but we can't signal it (different user)
        return True, pid


def start_daemon(run_func: Callable[..., Any], **kwargs: Any) -> None:
    """Fork process, write PID, redirect output to log.

    Uses double-fork to fully detach from terminal.

    Args:
        run_func: Function to run in the daemon process
        **kwargs: Arguments to pass to run_func
    """
    alive, pid = is_running()
    if alive:
        print(f"Runner already running (PID {pid}). Use 'ploston runner stop' first.")
        sys.exit(1)

    PLOSTON_DIR.mkdir(parents=True, exist_ok=True)

    # First fork - create child process
    pid = os.fork()
    if pid > 0:
        # Parent waits briefly, checks child started
        time.sleep(0.5)
        alive, child_pid = is_running()
        if alive:
            print(f"Runner started (PID {child_pid})")
            print(f"Logs: {LOG_FILE}")
        else:
            print("Runner failed to start. Check logs.")
            sys.exit(1)
        sys.exit(0)

    # Child: create new session to detach from terminal
    os.setsid()

    # Second fork - prevent zombie processes
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    # Grandchild: this is the actual daemon process
    # Write PID file
    PID_FILE.write_text(str(os.getpid()))

    # Redirect stdout/stderr to log file
    log_fd = open(LOG_FILE, "a")
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())

    # Handle signals for graceful shutdown
    def handle_sigterm(signum: int, frame: Any) -> None:
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    # Configure logging for daemon mode
    from ..shared.logging import configure_logging

    log_level = kwargs.pop("log_level", "info")
    configure_logging(level=log_level, log_file=LOG_FILE, json_output=True)

    # Run the actual runner
    run_func(**kwargs)


def stop_daemon() -> None:
    """Stop daemon via SIGTERM.

    Waits up to 5 seconds for graceful shutdown, then force-kills.
    """
    alive, pid = is_running()
    if not alive:
        print("Runner is not running.")
        return

    os.kill(pid, signal.SIGTERM)

    # Wait for shutdown (5s timeout)
    for _ in range(50):
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            PID_FILE.unlink(missing_ok=True)
            print(f"Runner stopped (was PID {pid}).")
            return

    # Force kill after timeout
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # Already dead

    PID_FILE.unlink(missing_ok=True)
    print(f"Runner force-killed (PID {pid}).")


def get_pid() -> int | None:
    """Get the PID of the running daemon.

    Returns:
        PID if running, None otherwise
    """
    alive, pid = is_running()
    return pid if alive else None
