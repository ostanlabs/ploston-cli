"""Inspector command — local web UI for MCP server discoverability.

Launches a local Starlette app on 127.0.0.1:7777 (by default) that mirrors
the CP's MCP surface (CP-hosted + runner-hosted + native tools) and fans
out live updates from the CP over SSE. By default the inspector runs as a
background daemon mirroring ``ploston runner`` ergonomics; ``--foreground``
restores the original blocking behaviour.
"""

import logging
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

import click

from ..inspector import daemon as inspector_daemon
from ..inspector.proxy import InspectorProxyError
from ..inspector.run import run_inspector_blocking, run_inspector_daemon
from ..shared.paths import INSPECTOR_LOG_FILE, get_token_file

DEFAULT_URL = "http://localhost:8022"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7777
DEFAULT_TIMEOUT = 30.0
DEFAULT_LOG_LEVEL = "info"
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_DELAY = 1.0

logger = logging.getLogger(__name__)


def _validate_url(ctx: click.Context, param: click.Parameter, value: str) -> str:
    if not value:
        raise click.BadParameter("URL is required")
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise click.BadParameter(f"Invalid URL format: {value}")
    return value


def _setup_foreground_logging(log_level: str, log_file: str | None) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    if log_file:
        log_path = Path(log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path)
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logging.root.addHandler(handler)
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logging.root.addHandler(stream)
    logging.root.setLevel(level)


def _persist_inspector_token(token: str) -> Path:
    """Write ``token`` to ``~/.ploston/tokens/inspector.token`` (mode 0o600)."""
    token_file = get_token_file("inspector")
    token_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    token_file.write_text(token)
    token_file.chmod(0o600)
    return token_file


def _read_inspector_token() -> str | None:
    token_file = get_token_file("inspector")
    if not token_file.exists():
        return None
    try:
        return token_file.read_text().strip() or None
    except OSError:
        return None


def _delete_inspector_token() -> None:
    get_token_file("inspector").unlink(missing_ok=True)


_LOOPBACK_LITERALS = {"127.0.0.1", "::1", "0.0.0.0", "::"}


def _display_host(host: str) -> str:
    """Map a bind literal to the host users actually want in their URL bar.

    Loopback IPs (and the wildcard binds, which always include loopback)
    render as ``localhost``; everything else is preserved verbatim.
    """
    return "localhost" if host in _LOOPBACK_LITERALS else host


def _open_browser_if_requested(open_browser: bool, host: str, port: int) -> None:
    if open_browser:
        # ``?t=<epoch>`` defeats Chrome's tab-reuse heuristic: when a tab is
        # already open at the bare URL (e.g. left over from a prior
        # ``stop``/``start`` cycle), ``webbrowser.open`` would otherwise
        # surface the stale page instead of forcing a navigation. The query
        # string is harmless to the inspector — Starlette ignores unknown
        # params.
        cache_buster = int(time.time())
        webbrowser.open(f"http://{_display_host(host)}:{port}/?t={cache_buster}")
        click.echo("  Browser opened.")


_START_OPTIONS = [
    click.option(
        "--url",
        envvar="PLOSTON_URL",
        default=DEFAULT_URL,
        callback=_validate_url,
        help=f"Control Plane URL (default: {DEFAULT_URL})",
    ),
    click.option("--token", envvar="PLOSTON_TOKEN", help="Bearer token for CP authentication"),
    click.option("--host", default=DEFAULT_HOST, help=f"Bind host (default: {DEFAULT_HOST})"),
    click.option(
        "--port", type=int, default=DEFAULT_PORT, help=f"Bind port (default: {DEFAULT_PORT})"
    ),
    click.option(
        "--open/--no-open",
        "open_browser",
        default=True,
        help="Open the inspector in a browser once it is ready",
    ),
    click.option(
        "--insecure",
        envvar="PLOSTON_INSECURE",
        is_flag=True,
        default=False,
        help="Skip SSL certificate verification (for self-signed certs)",
    ),
    click.option(
        "--timeout",
        envvar="PLOSTON_TIMEOUT",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"CP request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    ),
    click.option(
        "--retry-attempts",
        type=int,
        default=DEFAULT_RETRY_ATTEMPTS,
        help=f"Startup health check retries (default: {DEFAULT_RETRY_ATTEMPTS})",
    ),
    click.option(
        "--retry-delay",
        type=float,
        default=DEFAULT_RETRY_DELAY,
        help=f"Retry delay seconds (default: {DEFAULT_RETRY_DELAY})",
    ),
    click.option(
        "--log-level",
        envvar="PLOSTON_LOG_LEVEL",
        type=click.Choice(["debug", "info", "warning", "error"], case_sensitive=False),
        default=DEFAULT_LOG_LEVEL,
        help=f"Log level (default: {DEFAULT_LOG_LEVEL})",
    ),
    click.option(
        "--log-file",
        envvar="PLOSTON_LOG_FILE",
        default=None,
        help=f"Log file path (default: {INSPECTOR_LOG_FILE})",
    ),
    click.option(
        "--daemon/--foreground",
        default=True,
        help="Run as a background daemon (default) or block in the foreground",
    ),
]


def _apply_start_options(func):
    for opt in reversed(_START_OPTIONS):
        func = opt(func)
    return func


@click.group("inspector", invoke_without_command=True)
@click.pass_context
def inspector_command(ctx: click.Context) -> None:
    """Manage the Ploston Inspector — a local web UI for MCP discoverability.

    \b
    Smart default:
      ploston inspector              # start daemon if not running, else open browser
      ploston inspector start        # explicit start (defaults to --daemon)
      ploston inspector stop         # stop the running daemon
      ploston inspector status       # show daemon status
      ploston inspector logs [-f]    # tail the inspector log file
    """
    if ctx.invoked_subcommand is None:
        # Smart default: route to start with all-default options.
        ctx.invoke(start_command)


@inspector_command.command("start")
@_apply_start_options
def start_command(
    url: str,
    token: str | None,
    host: str,
    port: int,
    open_browser: bool,
    insecure: bool,
    timeout: float,
    retry_attempts: int,
    retry_delay: float,
    log_level: str,
    log_file: str | None,
    daemon: bool,
) -> None:
    """Start the Ploston Inspector (defaults to background daemon)."""
    if not 1 <= port <= 65535:
        raise click.BadParameter(f"Invalid port: {port}")

    log_path = Path(log_file).expanduser() if log_file else INSPECTOR_LOG_FILE
    alive, existing_pid = inspector_daemon.is_running()

    if alive and daemon:
        click.echo(
            f"Inspector already running (PID {existing_pid}) at http://{_display_host(host)}:{port}"
        )
        _open_browser_if_requested(open_browser, host, port)
        return

    if alive and not daemon:
        click.echo(
            f"Error: Inspector daemon already running (PID {existing_pid}). "
            "Use 'ploston inspector stop' first, or run a foreground inspector "
            "on a different --port.",
            err=True,
        )
        sys.exit(1)

    effective_token = token or _read_inspector_token()

    if daemon:
        if token:
            _persist_inspector_token(token)
        try:
            inspector_daemon.start_daemon(
                run_inspector_daemon,
                host=host,
                port=port,
                url=url,
                token=effective_token,
                insecure=insecure,
                timeout=timeout,
                retry_attempts=retry_attempts,
                retry_delay=retry_delay,
                log_level=log_level,
                log_file=log_path,
            )
        except SystemExit:
            raise
        # Parent reached this point: child exited the process tree via
        # ``sys.exit(0)`` from ``start_daemon``. Below executes only when the
        # forked grandchild is still going (it isn't, because the parent
        # ``sys.exit(0)``s); kept as a defensive no-op.
        _open_browser_if_requested(open_browser, host, port)
        return

    # Foreground path — preserves the original blocking behaviour.
    _setup_foreground_logging(log_level, str(log_path))
    click.echo("Ploston Inspector starting")
    click.echo(f"  CP:        {url}   [ok]")
    click.echo(f"  Listening: http://{_display_host(host)}:{port}")
    _open_browser_if_requested(open_browser, host, port)
    click.echo("  Press Ctrl+C to stop.")
    try:
        run_inspector_blocking(
            url=url,
            token=effective_token,
            host=host,
            port=port,
            insecure=insecure,
            timeout=timeout,
            retry_attempts=retry_attempts,
            retry_delay=retry_delay,
        )
    except KeyboardInterrupt:
        logger.info("[inspector] Interrupted by user")
        sys.exit(0)
    except InspectorProxyError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@inspector_command.command("stop")
def stop_command() -> None:
    """Stop the running inspector daemon (deletes any cached inspector token)."""
    inspector_daemon.stop_daemon(on_stopped=_delete_inspector_token)


def _format_bind_url(host: str, port: int) -> str:
    """Format ``host:port`` as an HTTP URL, bracketing IPv6 literals."""
    if ":" in host and not host.startswith("["):
        return f"http://[{host}]:{port}"
    return f"http://{host}:{port}"


@inspector_command.command("status")
def status_command() -> None:
    """Show inspector daemon status."""
    alive, pid = inspector_daemon.is_running()
    if not alive:
        click.echo("Inspector: not running")
        return

    click.echo("Inspector: running")
    click.echo(f"  PID: {pid}")
    state = inspector_daemon.read_state()
    if state is not None:
        port = state.get("port")
        bind_hosts = state.get("bind_hosts") or ([state.get("host")] if state.get("host") else [])
        urls = [_format_bind_url(h, port) for h in bind_hosts if h and port]
        if urls:
            click.echo(f"  URL: {urls[0]}")
            for extra in urls[1:]:
                click.echo(f"       {extra}")
        cp_url = state.get("url")
        if cp_url:
            click.echo(f"  CP:  {cp_url}")
    click.echo(f"  Logs: {INSPECTOR_LOG_FILE}")


@inspector_command.command("logs")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--lines", "-n", default=50, help="Number of lines to show")
def logs_command(follow: bool, lines: int) -> None:
    """Tail the inspector daemon log file."""
    if not INSPECTOR_LOG_FILE.exists():
        click.echo("No log file found.")
        return
    if follow:
        subprocess.run(["tail", "-f", str(INSPECTOR_LOG_FILE)])
    else:
        subprocess.run(["tail", "-n", str(lines), str(INSPECTOR_LOG_FILE)])
