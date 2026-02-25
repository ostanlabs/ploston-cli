"""MCP availability monitoring and reporting.

Handles:
- Testing MCPs on startup
- Periodic health checks
- Reporting availability to Control Plane
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ploston_core.config.models import MCPServerDefinition
from ploston_core.mcp import MCPClientManager
from ploston_core.types import ConnectionStatus

from .types import MCPAvailability, MCPConfig, MCPStatus, RunnerMCPConfig, ToolInfo

if TYPE_CHECKING:
    from .connection import RunnerConnection

logger = logging.getLogger(__name__)


class AvailabilityReporter:
    """Monitors MCP availability and reports to Control Plane.

    Tests MCPs on startup, performs periodic health checks,
    and reports availability changes to CP.
    """

    def __init__(
        self,
        connection: "RunnerConnection",
        health_check_interval: float = 30.0,
    ):
        """Initialize availability reporter.

        Args:
            connection: Runner connection to CP for reporting
            health_check_interval: Interval between health checks in seconds
        """
        self._connection = connection
        self._health_check_interval = health_check_interval
        self._mcp_manager: MCPClientManager | None = None
        self._availability: dict[str, MCPAvailability] = {}
        self._health_check_task: asyncio.Task[None] | None = None
        self._should_run = False

    @property
    def available_tools(self) -> list[str]:
        """List of all available tool names across all MCPs.

        Tool names are prefixed with MCP server name: mcp__toolname
        """
        tools = []
        for mcp_name, avail in self._availability.items():
            if avail.status == MCPStatus.AVAILABLE:
                for t in avail.tools:
                    tools.append(f"{mcp_name}__{t.name}")
        return tools

    @property
    def available_tools_with_schema(self) -> list[ToolInfo]:
        """List of all available tools with full schema across all MCPs.

        Tool names are prefixed with MCP server name: mcp__toolname
        """
        tools = []
        for mcp_name, avail in self._availability.items():
            if avail.status == MCPStatus.AVAILABLE:
                for t in avail.tools:
                    tools.append(
                        ToolInfo(
                            name=f"{mcp_name}__{t.name}",
                            description=t.description,
                            input_schema=t.input_schema,
                        )
                    )
        return tools

    @property
    def unavailable_mcps(self) -> list[str]:
        """List of unavailable MCP names."""
        return [
            name
            for name, avail in self._availability.items()
            if avail.status == MCPStatus.UNAVAILABLE
        ]

    def _mcp_config_to_server_def(self, config: MCPConfig) -> MCPServerDefinition:
        """Convert MCPConfig to MCPServerDefinition for ploston-core.

        Args:
            config: MCP configuration from CP

        Returns:
            MCPServerDefinition for MCPClientManager
        """
        if config.url:
            return MCPServerDefinition(
                url=config.url,
                transport="http",
            )
        else:
            if config.args:
                full_command = f"{config.command} {' '.join(config.args)}"
            else:
                full_command = config.command

            return MCPServerDefinition(
                command=full_command,
                env=config.env,
                transport="stdio",
            )

    async def initialize_mcps(self, config: RunnerMCPConfig) -> None:
        """Initialize MCPs from configuration and test availability.

        Args:
            config: MCP configuration from CP
        """
        logger.info(f"Initializing {len(config.mcps)} MCPs")

        from ploston_core.config.models import ToolsConfig

        mcp_servers = {
            name: self._mcp_config_to_server_def(mcp_config)
            for name, mcp_config in config.mcps.items()
        }

        tools_config = ToolsConfig(mcp_servers=mcp_servers)
        self._mcp_manager = MCPClientManager(config=tools_config)

        await self._test_all_mcps()
        await self._report_availability()

        self._should_run = True
        self._health_check_task = asyncio.create_task(self._health_check_loop())

    async def _test_all_mcps(self) -> None:
        """Test all configured MCPs and update availability."""
        if not self._mcp_manager:
            return

        statuses = await self._mcp_manager.connect_all()

        for name, status in statuses.items():
            now = datetime.now(UTC)

            if status.status == ConnectionStatus.CONNECTED:
                conn = self._mcp_manager.get_connection(name)
                tool_schemas = conn.list_tools() if conn else []
                tools = [
                    ToolInfo(
                        name=t.name,
                        description=t.description,
                        input_schema=t.input_schema,
                    )
                    for t in tool_schemas
                ]
                self._availability[name] = MCPAvailability(
                    name=name,
                    status=MCPStatus.AVAILABLE,
                    tools=tools,
                    last_checked=now,
                )
                logger.info(f"MCP '{name}' available with {len(tools)} tools")
            else:
                self._availability[name] = MCPAvailability(
                    name=name,
                    status=MCPStatus.UNAVAILABLE,
                    error=status.error,
                    last_checked=now,
                )
                logger.warning(f"MCP '{name}' unavailable: {status.error}")

    async def _report_availability(self) -> None:
        """Report current availability to Control Plane.

        Sends full tool schemas including name, description, and inputSchema.
        Tool names are prefixed with MCP server name using __ delimiter.
        """
        if not self._connection.is_connected:
            logger.warning("Cannot report availability: not connected to CP")
            return

        available = []
        unavailable = []

        for mcp_name, avail in self._availability.items():
            if avail.status == MCPStatus.AVAILABLE:
                for tool in avail.tools:
                    prefixed_name = f"{mcp_name}__{tool.name}"
                    available.append(
                        {
                            "name": prefixed_name,
                            "description": tool.description,
                            "inputSchema": tool.input_schema,
                        }
                    )
            else:
                unavailable.append(mcp_name)

        try:
            from .types import RunnerMethods

            await self._connection.send_notification(
                RunnerMethods.AVAILABILITY,
                {
                    "available": available,
                    "unavailable": unavailable,
                },
            )
            logger.debug(f"Reported availability: {len(available)} tools available")
        except Exception as e:
            logger.error(f"Failed to report availability: {e}")

    async def _health_check_loop(self) -> None:
        """Background task for periodic health checks."""
        while self._should_run:
            try:
                await asyncio.sleep(self._health_check_interval)
                await self._perform_health_checks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")

    async def _perform_health_checks(self) -> None:
        """Perform health checks on all MCPs."""
        if not self._mcp_manager:
            return

        statuses = self._mcp_manager.get_status()

        availability_changed = False
        now = datetime.now(UTC)

        for name, status in statuses.items():
            old_avail = self._availability.get(name)
            old_status = old_avail.status if old_avail else MCPStatus.UNKNOWN

            if status.status == ConnectionStatus.CONNECTED:
                new_status = MCPStatus.AVAILABLE
                conn = self._mcp_manager.get_connection(name)
                tool_schemas = conn.list_tools() if conn else []
                tools = [
                    ToolInfo(
                        name=t.name,
                        description=t.description,
                        input_schema=t.input_schema,
                    )
                    for t in tool_schemas
                ]
            else:
                new_status = MCPStatus.UNAVAILABLE
                tools = []

            if old_status != new_status:
                availability_changed = True
                logger.info(f"MCP '{name}' status changed: {old_status} -> {new_status}")

            self._availability[name] = MCPAvailability(
                name=name,
                status=new_status,
                tools=tools,
                error=status.error,
                last_checked=now,
            )

        if availability_changed:
            await self._report_availability()

    async def stop(self) -> None:
        """Stop health monitoring and disconnect MCPs."""
        self._should_run = False

        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

        if self._mcp_manager:
            await self._mcp_manager.disconnect_all()
            self._mcp_manager = None

        logger.info("Availability reporter stopped")

    def get_mcp_manager(self) -> MCPClientManager | None:
        """Get the MCP client manager for tool invocation.

        Returns:
            MCPClientManager if initialized, None otherwise
        """
        return self._mcp_manager

    def is_tool_available(self, tool_name: str) -> bool:
        """Check if a tool is available.

        Args:
            tool_name: Name of the tool

        Returns:
            True if tool is available
        """
        return tool_name in self.available_tools
