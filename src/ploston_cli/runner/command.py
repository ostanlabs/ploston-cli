"""Runner execution logic.

Provides the run_runner function that is called by the CLI commands
in main.py for both daemon and foreground modes.
"""

import logging

logger = logging.getLogger(__name__)


def run_runner(cp: str, token: str, name: str) -> None:
    """Execute the runner (called in daemon or foreground mode).

    This is the main entry point for runner execution. It:
    1. Creates a RunnerConfig from the provided parameters
    2. Creates a RunnerConnection with all handlers wired up
    3. Runs the connection's main loop

    Args:
        cp: Control Plane WebSocket URL (e.g., wss://ploston:8022/runner/ws)
        token: Runner authentication token
        name: Runner name (unique identifier)
    """
    import asyncio

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
