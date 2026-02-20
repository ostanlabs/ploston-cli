"""Bridge command - MCP stdio-to-HTTP transport.

Translates between stdio MCP (agent-facing) and HTTP+SSE MCP (CP-facing).
Enables Claude Desktop, Cursor, and other stdio MCP clients to connect
to remote Ploston Control Plane.
"""

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path
from urllib.parse import urlparse

import click

from ..bridge.proxy import BridgeProxy, BridgeProxyError
from ..bridge.server import BridgeServer

# Default values
DEFAULT_TIMEOUT = 30.0
DEFAULT_LOG_LEVEL = "info"
DEFAULT_LOG_FILE = "~/.ploston/bridge.log"
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_DELAY = 1.0

logger = logging.getLogger(__name__)


def validate_url(ctx: click.Context, param: click.Parameter, value: str) -> str:
    """Validate URL format."""
    if not value:
        raise click.BadParameter("URL is required")

    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise click.BadParameter(f"Invalid URL format: {value}")

    return value


def setup_logging(log_level: str, log_file: str | None) -> None:
    """Configure logging for bridge.

    Note: We log to file only, not stdout (would disrupt stdio protocol).
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Expand ~ in path
    if log_file:
        log_path = Path(log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        handler = logging.FileHandler(log_path)
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logging.root.addHandler(handler)

    logging.root.setLevel(level)


@click.command("bridge")
@click.option(
    "--url",
    envvar="PLOSTON_URL",
    callback=validate_url,
    required=True,
    help="Control Plane URL (e.g., http://localhost:8080)",
)
@click.option(
    "--token",
    envvar="PLOSTON_TOKEN",
    help="Bearer token for authentication",
)
@click.option(
    "--timeout",
    envvar="PLOSTON_TIMEOUT",
    type=float,
    default=DEFAULT_TIMEOUT,
    help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})",
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
@click.option(
    "--retry-attempts",
    envvar="PLOSTON_RETRY_ATTEMPTS",
    type=int,
    default=DEFAULT_RETRY_ATTEMPTS,
    help=f"Number of retry attempts for startup health check (default: {DEFAULT_RETRY_ATTEMPTS})",
)
@click.option(
    "--retry-delay",
    envvar="PLOSTON_RETRY_DELAY",
    type=float,
    default=DEFAULT_RETRY_DELAY,
    help=f"Delay between retries in seconds (default: {DEFAULT_RETRY_DELAY})",
)
def bridge_command(
    url: str,
    token: str | None,
    timeout: float,
    log_level: str,
    log_file: str | None,
    retry_attempts: int,
    retry_delay: float,
) -> None:
    """Start MCP bridge to Control Plane.

    Translates stdio MCP protocol to HTTP+SSE for connecting
    Claude Desktop, Cursor, and other MCP clients to Ploston.

    \b
    Example usage:
      ploston bridge --url http://localhost:8080
      ploston bridge --url https://cp.example.com --token plt_xxx

    \b
    Environment variables:
      PLOSTON_URL       - Control Plane URL
      PLOSTON_TOKEN     - Bearer token
      PLOSTON_TIMEOUT   - Request timeout
      PLOSTON_LOG_LEVEL - Log level
      PLOSTON_LOG_FILE  - Log file path
    """
    # Setup logging (to file, not stdout)
    setup_logging(log_level, log_file)

    logger.info(f"Starting bridge to {url}")

    try:
        asyncio.run(run_bridge(url, token, timeout, retry_attempts, retry_delay))
    except KeyboardInterrupt:
        logger.info("Bridge interrupted by user")
        sys.exit(0)
    except BridgeProxyError as e:
        logger.error(f"Bridge error: {e.message}")
        # Write error to stderr (not stdout)
        print(f"Error: {e.message}", file=sys.stderr)
        sys.exit(1)


async def run_bridge(
    url: str,
    token: str | None,
    timeout: float,
    retry_attempts: int,
    retry_delay: float,
) -> None:
    """Run the bridge main loop."""
    proxy = BridgeProxy(url=url, token=token, timeout=timeout)
    server = BridgeServer(proxy=proxy)

    # Startup health check with retry
    for attempt in range(retry_attempts):
        try:
            health = await proxy.health_check()
            logger.info(f"Connected to CP: {health}")
            break
        except BridgeProxyError as e:
            if attempt < retry_attempts - 1:
                logger.warning(f"Health check failed (attempt {attempt + 1}): {e.message}")
                await asyncio.sleep(retry_delay * (2**attempt))  # Exponential backoff
            else:
                raise BridgeProxyError(
                    code=e.code,
                    message=f"Failed to connect to CP after {retry_attempts} attempts: {e.message}",
                )

    # Setup signal handlers for graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Received shutdown signal")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    # Main loop: read from stdin, process, write to stdout
    try:
        await stdio_loop(server, shutdown_event)
    finally:
        logger.info("Bridge shutting down")
        await proxy.close()


async def stdio_loop(server: BridgeServer, shutdown_event: asyncio.Event) -> None:
    """Main stdio loop - read JSON-RPC from stdin, write responses to stdout."""
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)

    loop = asyncio.get_running_loop()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while not shutdown_event.is_set():
        try:
            # Read line from stdin (JSON-RPC messages are newline-delimited)
            line = await asyncio.wait_for(reader.readline(), timeout=1.0)

            if not line:
                # EOF - stdin closed
                logger.info("stdin closed")
                break

            line = line.decode("utf-8").strip()
            if not line:
                continue

            # Parse JSON-RPC request
            try:
                request = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON: {e}")
                continue

            # Handle request
            response = await server.handle_request(request)

            # Write response to stdout
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

        except asyncio.TimeoutError:
            # No input, check shutdown and continue
            continue
        except Exception as e:
            logger.exception(f"Error in stdio loop: {e}")
            break
