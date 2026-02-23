"""Bridge command - MCP stdio-to-HTTP transport.

Translates between stdio MCP (agent-facing) and HTTP+SSE MCP (CP-facing).
Enables Claude Desktop, Cursor, and other stdio MCP clients to connect
to remote Ploston Control Plane.

Debug mode:
    Set PLOSTON_DEBUG=1 or use --log-level debug to enable detailed logging.
    Logs are written to ~/.ploston/bridge.log (or custom path via --log-file).

    Example:
        PLOSTON_DEBUG=1 ploston bridge --url http://localhost:8443

    To tail logs in real-time:
        tail -f ~/.ploston/bridge.log
"""

import asyncio
import json
import logging
import os
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

# Check for debug mode via environment variable
DEBUG_MODE = os.environ.get("PLOSTON_DEBUG", "").lower() in ("1", "true", "yes")

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
    # Override log level if PLOSTON_DEBUG is set
    if DEBUG_MODE:
        log_level = "debug"

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
@click.option(
    "--insecure",
    envvar="PLOSTON_INSECURE",
    is_flag=True,
    default=False,
    help="Skip SSL certificate verification (for self-signed certs)",
)
@click.option(
    "--tools",
    envvar="PLOSTON_TOOLS",
    type=click.Choice(["all", "local", "native"], case_sensitive=False),
    default="all",
    help="Which tools to expose to the agent: all (default), local (runner only), native (native-tools only)",
)
def bridge_command(
    url: str,
    token: str | None,
    timeout: float,
    log_level: str,
    log_file: str | None,
    retry_attempts: int,
    retry_delay: float,
    insecure: bool,
    tools: str,
) -> None:
    """Start MCP bridge to Control Plane.

    Translates stdio MCP protocol to HTTP+SSE for connecting
    Claude Desktop, Cursor, and other MCP clients to Ploston.

    \b
    Example usage:
      ploston bridge --url http://localhost:8080
      ploston bridge --url https://cp.example.com --token plt_xxx
      ploston bridge --url http://localhost:8080 --tools local

    \b
    Tool filtering (--tools):
      all    - All tools: native-tools + local-runner + MCP servers (default)
      local  - Local runner tools only (from connected runners)
      native - Native tools only (filesystem, kafka, etc.)

    \b
    Environment variables:
      PLOSTON_URL       - Control Plane URL
      PLOSTON_TOKEN     - Bearer token
      PLOSTON_TIMEOUT   - Request timeout
      PLOSTON_LOG_LEVEL - Log level (debug, info, warning, error)
      PLOSTON_LOG_FILE  - Log file path
      PLOSTON_INSECURE  - Skip SSL verification
      PLOSTON_TOOLS     - Tool filter (all, local, native)
      PLOSTON_DEBUG     - Enable debug logging (set to 1)

    \b
    Debug mode:
      PLOSTON_DEBUG=1 ploston bridge --url http://localhost:8443
      tail -f ~/.ploston/bridge.log
    """
    # Setup logging (to file, not stdout)
    setup_logging(log_level, log_file)

    effective_log_level = "debug" if DEBUG_MODE else log_level

    logger.info(f"Starting bridge to {url}")
    logger.info(f"Debug mode: {DEBUG_MODE}, Log level: {effective_log_level}, Tools: {tools}")

    try:
        asyncio.run(run_bridge(url, token, timeout, retry_attempts, retry_delay, insecure, tools))
    except KeyboardInterrupt:
        logger.info("Bridge interrupted by user")
        sys.exit(0)
    except BridgeProxyError as e:
        logger.error(f"Bridge error: {e.message}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)


async def run_bridge(
    url: str,
    token: str | None,
    timeout: float,
    retry_attempts: int,
    retry_delay: float,
    insecure: bool = False,
    tools_filter: str = "all",
) -> None:
    """Run the bridge main loop."""
    proxy = BridgeProxy(url=url, token=token, timeout=timeout, insecure=insecure)
    server = BridgeServer(proxy=proxy, tools_filter=tools_filter)

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
    shutdown_requested = False

    def signal_handler() -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            # Second signal - force exit
            logger.info("Received second shutdown signal, forcing exit")
            return
        shutdown_requested = True
        logger.info("Received shutdown signal, stopping gracefully...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Signal handlers not supported on this platform (e.g., Windows)
            logger.debug(f"Signal handler for {sig} not supported on this platform")

    # Main loop: read from stdin, process, write to stdout
    try:
        await stdio_loop(server, shutdown_event)
    except asyncio.CancelledError:
        logger.info("Bridge task cancelled")
    finally:
        logger.info("Bridge shutting down, closing connections...")
        try:
            await asyncio.wait_for(proxy.close(), timeout=5.0)
            logger.info("Bridge shutdown complete")
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for proxy to close")
        except Exception as e:
            logger.warning(f"Error during shutdown: {e}")


def _format_request_for_log(request: dict) -> str:
    """Format request for debug logging (truncate large payloads)."""
    method = request.get("method", "unknown")
    request_id = request.get("id", "notification")
    params = request.get("params", {})

    # For tools/call, show tool name and truncated args
    if method == "tools/call":
        tool_name = params.get("name", "unknown")
        args = params.get("arguments", {})
        args_str = json.dumps(args)
        if len(args_str) > 200:
            args_str = args_str[:200] + "..."
        return f"[{request_id}] {method} -> {tool_name} args={args_str}"

    return f"[{request_id}] {method}"


def _format_response_for_log(response: dict) -> str:
    """Format response for debug logging (truncate large payloads)."""
    request_id = response.get("id", "?")

    if "error" in response:
        error = response["error"]
        return f"[{request_id}] ERROR: {error.get('code')} - {error.get('message')}"

    result = response.get("result", {})
    result_str = json.dumps(result)
    if len(result_str) > 500:
        result_str = result_str[:500] + "..."
    return f"[{request_id}] OK: {result_str}"


async def stdio_loop(server: BridgeServer, shutdown_event: asyncio.Event) -> None:
    """Main stdio loop - read JSON-RPC from stdin, write responses to stdout."""
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)

    loop = asyncio.get_running_loop()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    logger.debug("stdio loop started, waiting for requests...")

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

            # Debug log the incoming request
            logger.debug(f">>> REQUEST: {_format_request_for_log(request)}")

            # Handle request
            response = await server.handle_request(request)

            # Write response to stdout (only for requests, not notifications)
            # JSON-RPC notifications don't get responses, so handle_request returns None
            if response is not None:
                # Debug log the response
                logger.debug(f"<<< RESPONSE: {_format_response_for_log(response)}")

                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

        except asyncio.TimeoutError:
            # No input, check shutdown and continue
            continue
        except asyncio.CancelledError:
            # Task was cancelled (e.g., during shutdown)
            logger.debug("stdio loop cancelled")
            break
        except Exception as e:
            logger.exception(f"Error in stdio loop: {e}")
            break

    logger.debug("stdio loop exiting")
