"""Inspector command — local web UI for MCP server discoverability.

Launches a local Starlette app on 127.0.0.1:7777 (by default) that mirrors
the CP's MCP surface (CP-hosted + runner-hosted + native tools) and fans
out live updates from the CP over SSE.
"""

import asyncio
import logging
import signal
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

import click

from ..inspector.proxy import InspectorProxy, InspectorProxyError
from ..inspector.server import run_inspector_server

DEFAULT_URL = "http://localhost:8022"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7777
DEFAULT_TIMEOUT = 30.0
DEFAULT_LOG_LEVEL = "info"
DEFAULT_LOG_FILE = "~/.ploston/inspector.log"
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


def _setup_logging(log_level: str, log_file: str | None) -> None:
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


@click.command("inspector")
@click.option(
    "--url",
    envvar="PLOSTON_URL",
    default=DEFAULT_URL,
    callback=_validate_url,
    help=f"Control Plane URL (default: {DEFAULT_URL})",
)
@click.option("--token", envvar="PLOSTON_TOKEN", help="Bearer token for CP authentication")
@click.option("--host", default=DEFAULT_HOST, help=f"Bind host (default: {DEFAULT_HOST})")
@click.option("--port", type=int, default=DEFAULT_PORT, help=f"Bind port (default: {DEFAULT_PORT})")
@click.option(
    "--open/--no-open",
    "open_browser",
    default=True,
    help="Open the inspector in a browser on startup",
)
@click.option(
    "--insecure",
    envvar="PLOSTON_INSECURE",
    is_flag=True,
    default=False,
    help="Skip SSL certificate verification (for self-signed certs)",
)
@click.option(
    "--timeout",
    envvar="PLOSTON_TIMEOUT",
    type=float,
    default=DEFAULT_TIMEOUT,
    help=f"CP request timeout in seconds (default: {DEFAULT_TIMEOUT})",
)
@click.option(
    "--retry-attempts",
    type=int,
    default=DEFAULT_RETRY_ATTEMPTS,
    help=f"Startup health check retries (default: {DEFAULT_RETRY_ATTEMPTS})",
)
@click.option(
    "--retry-delay",
    type=float,
    default=DEFAULT_RETRY_DELAY,
    help=f"Retry delay seconds (default: {DEFAULT_RETRY_DELAY})",
)
@click.option(
    "--log-level",
    envvar="PLOSTON_LOG_LEVEL",
    type=click.Choice(["debug", "info", "warning", "error"], case_sensitive=False),
    default=DEFAULT_LOG_LEVEL,
    help=f"Log level (default: {DEFAULT_LOG_LEVEL})",
)
@click.option(
    "--log-file",
    envvar="PLOSTON_LOG_FILE",
    default=DEFAULT_LOG_FILE,
    help=f"Log file path (default: {DEFAULT_LOG_FILE})",
)
def inspector_command(
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
) -> None:
    """Start the Ploston Inspector — a local web UI for MCP discoverability.

    \b
    Example usage:
      ploston inspector
      ploston inspector --url http://localhost:8022
      ploston inspector --port 8080 --no-open
    """
    _setup_logging(log_level, log_file)

    if not 1 <= port <= 65535:
        raise click.BadParameter(f"Invalid port: {port}")

    try:
        asyncio.run(
            _run(
                url, token, host, port, open_browser, insecure, timeout, retry_attempts, retry_delay
            )
        )
    except KeyboardInterrupt:
        logger.info("[inspector] Interrupted by user")
        sys.exit(0)
    except InspectorProxyError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


async def _run(
    url, token, host, port, open_browser, insecure, timeout, retry_attempts, retry_delay
) -> None:
    proxy = InspectorProxy(url=url, token=token, timeout=timeout, insecure=insecure)

    # Startup health check with exponential backoff
    for attempt in range(retry_attempts):
        try:
            await proxy.health()
            logger.info(f"[inspector] Connected to CP at {url}")
            break
        except InspectorProxyError as e:
            if attempt < retry_attempts - 1:
                logger.warning(f"[inspector] Health check failed (attempt {attempt + 1}): {e}")
                await asyncio.sleep(retry_delay * (2**attempt))
            else:
                await proxy.close()
                raise InspectorProxyError(
                    f"Failed to connect to CP after {retry_attempts} attempts: {e}"
                ) from e

    click.echo("Ploston Inspector starting")
    click.echo(f"  CP:        {url}   [ok]")
    click.echo(f"  Listening: http://{host}:{port}")

    if open_browser:
        webbrowser.open(f"http://{host}:{port}")
        click.echo("  Browser opened.")
    click.echo("  Press Ctrl+C to stop.")

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            pass

    try:
        await run_inspector_server(proxy=proxy, host=host, port=port, shutdown_event=shutdown_event)
    finally:
        await proxy.close()
