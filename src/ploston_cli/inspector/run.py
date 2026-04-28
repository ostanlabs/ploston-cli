"""Inspector runtime entry points.

Two entry points share a single async core:

* ``run_inspector_blocking`` — used by foreground (``--foreground``) mode.
  Runs ``run_inspector_server`` until SIGINT/SIGTERM and writes user-facing
  banner output to stdout.

* ``run_inspector_daemon`` — used by the daemon path. Configures file logging
  to ``inspector.log`` (since stdout is already redirected by the daemon
  scaffolding) and waits on the same async core. Suitable for invocation
  in the grandchild after the double-fork.
"""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path

from .proxy import InspectorProxy, InspectorProxyError
from .server import run_inspector_server

logger = logging.getLogger(__name__)


async def _serve(
    *,
    url: str,
    token: str | None,
    host: str,
    port: int,
    insecure: bool,
    timeout: float,
    retry_attempts: int,
    retry_delay: float,
    on_ready: Callable[[InspectorProxy], Awaitable[None]] | None = None,
) -> None:
    proxy = InspectorProxy(url=url, token=token, timeout=timeout, insecure=insecure)
    for attempt in range(retry_attempts):
        try:
            await proxy.health()
            logger.info("[inspector] Connected to CP at %s", url)
            break
        except InspectorProxyError as exc:
            if attempt < retry_attempts - 1:
                logger.warning("[inspector] Health check failed (attempt %d): %s", attempt + 1, exc)
                await asyncio.sleep(retry_delay * (2**attempt))
            else:
                await proxy.close()
                raise InspectorProxyError(
                    f"Failed to connect to CP after {retry_attempts} attempts: {exc}"
                ) from exc

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            pass

    if on_ready is not None:
        await on_ready(proxy)

    try:
        await run_inspector_server(proxy=proxy, host=host, port=port, shutdown_event=shutdown_event)
    finally:
        await proxy.close()


def run_inspector_daemon(
    *,
    url: str,
    token: str | None,
    host: str,
    port: int,
    insecure: bool,
    timeout: float,
    retry_attempts: int,
    retry_delay: float,
    log_level: str = "info",
    log_file: Path | None = None,
) -> None:
    """Daemon-side entry point. Runs the async server until a signal arrives."""
    from ..shared.logging import configure_logging

    configure_logging(level=log_level, log_file=log_file, json_output=True)
    try:
        asyncio.run(
            _serve(
                url=url,
                token=token,
                host=host,
                port=port,
                insecure=insecure,
                timeout=timeout,
                retry_attempts=retry_attempts,
                retry_delay=retry_delay,
            )
        )
    except InspectorProxyError as exc:
        logger.error("[inspector] %s", exc)
        raise


def run_inspector_blocking(
    *,
    url: str,
    token: str | None,
    host: str,
    port: int,
    insecure: bool,
    timeout: float,
    retry_attempts: int,
    retry_delay: float,
    on_ready: Callable[[InspectorProxy], Awaitable[None]] | None = None,
) -> None:
    """Foreground entry point. Same async core, used by ``--foreground``."""
    asyncio.run(
        _serve(
            url=url,
            token=token,
            host=host,
            port=port,
            insecure=insecure,
            timeout=timeout,
            retry_attempts=retry_attempts,
            retry_delay=retry_delay,
            on_ready=on_ready,
        )
    )
