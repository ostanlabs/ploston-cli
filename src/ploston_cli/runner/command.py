"""Runner execution logic.

Provides the run_runner function that is called by the CLI commands
in main.py for both daemon and foreground modes.
"""


def run_runner(cp: str, token: str, name: str) -> None:
    """Execute the runner (called in daemon or foreground mode).

    This is the main entry point for runner execution. It:
    1. Creates a RunnerConfig from the provided parameters
    2. Creates a RunnerConnection
    3. Runs the connection's main loop

    Args:
        cp: Control Plane WebSocket URL (e.g., wss://ploston:8443/runner)
        token: Runner authentication token
        name: Runner name (unique identifier)
    """
    import asyncio

    from .connection import RunnerConnection
    from .types import RunnerConfig

    async def _run() -> None:
        config = RunnerConfig(
            control_plane_url=cp,
            auth_token=token,
            runner_name=name,
        )
        conn = RunnerConnection(config=config)
        await conn.run()

    asyncio.run(_run())
