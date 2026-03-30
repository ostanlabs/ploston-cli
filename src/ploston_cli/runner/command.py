"""Runner execution logic.

Provides the run_runner function that is called by the CLI commands
in main.py for both daemon and foreground modes.
"""

import logging
import os

logger = logging.getLogger(__name__)


def _load_ploston_env() -> None:
    """Load ~/.ploston/.env into os.environ.

    MCP server configs pushed from the CP reference secrets via ``${VAR}``
    syntax.  ``ConfigReceiver._resolve_env_vars`` resolves them from
    ``os.environ``, so the values must be present in the process environment
    before any config/push arrives.

    Only variables that are **not** already set are injected (so explicit
    exports or CLI-level overrides take precedence).
    """
    from ..init.env_manager import load_env_file

    env_vars = load_env_file()  # reads ~/.ploston/.env
    for key, value in env_vars.items():
        if key not in os.environ:
            os.environ[key] = value
            logger.debug("Loaded env var %s from ~/.ploston/.env", key)
        else:
            logger.debug("Env var %s already set, skipping", key)


def run_runner(cp: str, token: str, name: str) -> None:
    """Execute the runner (called in daemon or foreground mode).

    This is the main entry point for runner execution. It:
    1. Loads secrets from ~/.ploston/.env into os.environ
    2. Creates a RunnerConfig from the provided parameters
    3. Creates a RunnerConnection with all handlers wired up
    4. Runs the connection's main loop

    Args:
        cp: Control Plane WebSocket URL (e.g., wss://ploston:8022/runner/ws)
        token: Runner authentication token
        name: Runner name (unique identifier)
    """
    import asyncio

    # Load secrets (GITHUB_PERSONAL_ACCESS_TOKEN, etc.) so ConfigReceiver
    # can resolve ${VAR} references in MCP server env configs.
    _load_ploston_env()

    from .availability import AvailabilityReporter
    from .config_receiver import ConfigReceiver
    from .connection import RunnerConnection
    from .executor import WorkflowExecutor
    from .proxy import ToolProxy
    from .types import RunnerConfig, RunnerMCPConfig

    async def _run() -> None:
        config = RunnerConfig(
            control_plane_url=cp,
            auth_token=token,
            runner_name=name,
        )

        # Create connection first (needed by other components)
        conn = RunnerConnection(config=config)

        # Create availability reporter (monitors MCPs and reports to CP)
        availability = AvailabilityReporter(connection=conn)

        # Wire reconnection callback to re-report MCP availability after reconnect
        async def on_reconnect() -> None:
            """Re-report availability after successful reconnection."""
            logger.info("Re-reporting MCP availability after reconnect")
            await availability._report_availability()

        conn._on_reconnect = on_reconnect

        # Create tool proxy (for proxying unavailable tools to CP)
        tool_proxy = ToolProxy(connection=conn, availability_reporter=availability)

        # Create workflow executor (handles workflow/execute and tool/call)
        executor = WorkflowExecutor(
            availability_reporter=availability,
            tool_proxy=tool_proxy,
        )

        # Create config receiver with callback to initialize MCPs
        async def on_config_received(mcp_config: RunnerMCPConfig) -> None:
            """Handle received MCP configuration."""
            logger.info(f"Received config with {len(mcp_config.mcps)} MCPs")
            await availability.initialize_mcps(mcp_config)
            await executor.initialize()

        config_receiver = ConfigReceiver(on_config_received=on_config_received)

        # Wire up handlers to connection
        conn.set_handlers(
            on_config_push=config_receiver.handle_config_push,
            on_workflow_execute=executor.handle_workflow_execute,
            on_tool_call=executor.handle_tool_call,
        )

        try:
            await conn.run()
        finally:
            await availability.stop()

    asyncio.run(_run())
