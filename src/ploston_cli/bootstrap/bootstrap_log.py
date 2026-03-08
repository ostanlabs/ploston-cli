"""File-based bootstrap debug logger.

Writes a detailed ``bootstrap.log`` in the current working directory every
time ``ploston bootstrap`` runs.  The log captures:

* Every subprocess invocation (command, cwd, exit code, stdout, stderr)
* Timing for each step and the overall bootstrap
* Docker / Docker Compose environment details
* Compose file contents
* Network and container state before and after deploy

The logger is intentionally *not* wired through Python ``logging`` — it writes
directly to a file so that it is always available regardless of log-level
configuration.
"""

from __future__ import annotations

import datetime as _dt
import os
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_log_path: Path | None = None
_start_time: _dt.datetime | None = None


def init(log_dir: Path | None = None) -> Path:
    """Initialise the bootstrap log file.

    Call this once at the very start of ``_run_bootstrap``.

    Args:
        log_dir: Directory to write ``bootstrap.log`` into.
                 Defaults to the current working directory.

    Returns:
        Absolute path to the log file.
    """
    global _log_path, _start_time  # noqa: PLW0603

    _start_time = _dt.datetime.now()
    target_dir = log_dir or Path.cwd()
    target_dir.mkdir(parents=True, exist_ok=True)
    _log_path = target_dir / "bootstrap.log"

    # Truncate any previous log
    _log_path.write_text("")

    _write_header()
    return _log_path


def _write_header() -> None:
    """Write the opening header with environment info."""
    section("Bootstrap Log")
    info("timestamp", _start_time.isoformat() if _start_time else "unknown")
    info("cwd", os.getcwd())
    info("uid", str(os.getuid()))
    info("PATH", os.environ.get("PATH", "(unset)"))
    info("DOCKER_HOST", os.environ.get("DOCKER_HOST", "(unset)"))
    info("COMPOSE_FILE", os.environ.get("COMPOSE_FILE", "(unset)"))

    # Docker version
    _run_and_log(
        ["docker", "version", "--format", "{{.Server.Version}}"], label="docker server version"
    )
    _run_and_log(["docker", "compose", "version", "--short"], label="docker compose version")
    _run_and_log(
        [
            "docker",
            "info",
            "--format",
            "{{.ServerVersion}} | OS={{.OperatingSystem}} | Driver={{.Driver}}",
        ],
        label="docker info",
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def section(title: str) -> None:
    """Write a section separator."""
    _append(f"\n{'=' * 72}\n  {title}\n{'=' * 72}\n")


def step(name: str) -> None:
    """Mark the beginning of a bootstrap step."""
    now = _dt.datetime.now()
    elapsed = ""
    if _start_time:
        elapsed = f"  [+{(now - _start_time).total_seconds():.1f}s]"
    _append(f"\n--- {name}{elapsed} ---\n")


def info(key: str, value: str) -> None:
    """Log a key-value pair."""
    _append(f"  {key}: {value}")


def detail(msg: str) -> None:
    """Log a free-form detail line."""
    _append(f"  {msg}")


def log_file_contents(path: Path | str, label: str | None = None) -> None:
    """Dump the contents of a file into the log."""
    p = Path(path)
    tag = label or str(p)
    _append(f"\n  ┌── {tag} ──")
    try:
        contents = p.read_text()
        for line in contents.splitlines():
            _append(f"  │ {line}")
    except Exception as exc:
        _append(f"  │ (could not read: {exc})")
    _append(f"  └── end {tag} ──\n")


def log_subprocess(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    label: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and log everything about it.

    This is a drop-in replacement for ``subprocess.run(..., capture_output=True, text=True)``.
    """
    return _run_and_log(args, cwd=cwd, label=label, env=env, capture=True)


def log_docker_state(label: str = "Docker state") -> None:
    """Snapshot current Docker container and network state into the log."""
    _append(f"\n  ┌── {label} ──")
    _run_and_log(
        ["docker", "ps", "-a", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"],
        label="docker ps -a",
    )
    _run_and_log(
        ["docker", "network", "ls", "--format", "table {{.Name}}\t{{.Driver}}\t{{.ID}}"],
        label="docker network ls",
    )
    _append(f"  └── end {label} ──\n")


def finish(success: bool, message: str = "") -> None:
    """Write the closing footer."""
    now = _dt.datetime.now()
    elapsed = (now - _start_time).total_seconds() if _start_time else 0
    section("Bootstrap Finished")
    info("result", "SUCCESS" if success else "FAILURE")
    if message:
        info("message", message)
    info("total_elapsed", f"{elapsed:.1f}s")
    info("finished_at", now.isoformat())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_and_log(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    label: str | None = None,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a command and append full details to the log."""
    tag = label or " ".join(args)
    _append(f"\n  ▸ [{tag}]")
    _append(f"    cmd: {' '.join(args)}")
    if cwd:
        _append(f"    cwd: {cwd}")

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
        )
    except FileNotFoundError as exc:
        _append(f"    ERROR: command not found — {exc}")
        return subprocess.CompletedProcess(args, returncode=-1, stdout="", stderr=str(exc))
    except Exception as exc:
        _append(f"    ERROR: {exc}")
        return subprocess.CompletedProcess(args, returncode=-1, stdout="", stderr=str(exc))

    _append(f"    exit: {result.returncode}")
    if result.stdout.strip():
        _append("    stdout:")
        for line in result.stdout.strip().splitlines():
            _append(f"      {line}")
    if result.stderr.strip():
        _append("    stderr:")
        for line in result.stderr.strip().splitlines():
            _append(f"      {line}")

    return result


def _append(line: str) -> None:
    """Append a line to the log file (no-op if not initialised)."""
    if _log_path is None:
        return
    try:
        with _log_path.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass  # Never let logging break the bootstrap
