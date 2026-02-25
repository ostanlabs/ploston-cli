"""Tool proxy for forwarding unavailable tool calls to Control Plane.

Handles:
- Detecting when a tool is unavailable locally
- Proxying tool calls to CP
- Returning results from CP
"""

import logging
from typing import TYPE_CHECKING, Any

from .types import RunnerMethods

if TYPE_CHECKING:
    from .availability import AvailabilityReporter
    from .connection import RunnerConnection

logger = logging.getLogger(__name__)


class ToolProxy:
    """Proxies tool calls to Control Plane for unavailable tools.

    When a workflow running on the runner needs a tool that isn't
    available locally, this proxy forwards the call to CP.
    """

    def __init__(
        self,
        connection: "RunnerConnection",
        availability_reporter: "AvailabilityReporter",
        timeout: float = 60.0,
    ):
        """Initialize tool proxy.

        Args:
            connection: Runner connection to CP
            availability_reporter: For checking tool availability
            timeout: Timeout for proxied tool calls in seconds
        """
        self._connection = connection
        self._availability = availability_reporter
        self._timeout = timeout

    def is_tool_available_locally(self, tool_name: str) -> bool:
        """Check if a tool is available locally.

        Args:
            tool_name: Name of the tool

        Returns:
            True if tool is available locally
        """
        return self._availability.is_tool_available(tool_name)

    async def proxy_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Proxy a tool call to Control Plane.

        Args:
            tool_name: Name of the tool to call
            args: Tool arguments
            timeout: Optional timeout override

        Returns:
            Tool call result from CP

        Raises:
            ConnectionError: If not connected to CP
            TimeoutError: If call times out
        """
        if not self._connection.is_connected:
            raise ConnectionError("Not connected to Control Plane")

        logger.info(f"Proxying tool call '{tool_name}' to Control Plane")

        try:
            response = await self._connection.send_request(
                RunnerMethods.TOOL_PROXY,
                {
                    "tool": tool_name,
                    "args": args,
                },
                timeout=timeout or self._timeout,
            )

            if response.get("error"):
                error = response["error"]
                logger.error(f"Proxied tool call failed: {error.get('message')}")
                return {
                    "status": "error",
                    "error": error,
                }

            result = response.get("result", {})
            logger.debug(f"Proxied tool call '{tool_name}' completed")
            return result

        except TimeoutError:
            logger.error(f"Proxied tool call '{tool_name}' timed out")
            raise
        except Exception as e:
            logger.error(f"Proxied tool call '{tool_name}' failed: {e}")
            raise

    async def invoke_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        local_invoker: Any | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Invoke a tool, either locally or via proxy.

        Args:
            tool_name: Name of the tool to call
            args: Tool arguments
            local_invoker: Optional local ToolInvoker for local calls
            timeout: Optional timeout

        Returns:
            Tool call result
        """
        # Check if tool is available locally
        if self.is_tool_available_locally(tool_name):
            if local_invoker:
                logger.debug(f"Invoking tool '{tool_name}' locally")
                return await local_invoker.invoke(tool_name=tool_name, params=args)
            else:
                logger.warning(f"Tool '{tool_name}' available but no local invoker")

        # Proxy to CP
        return await self.proxy_tool_call(tool_name, args, timeout)


class ProxyToolInvoker:
    """Tool invoker that supports proxying to CP.

    Wraps the standard ToolInvoker to add proxy support for
    unavailable tools.
    """

    def __init__(
        self,
        local_invoker: Any,
        tool_proxy: ToolProxy,
    ):
        """Initialize proxy tool invoker.

        Args:
            local_invoker: Local ToolInvoker for available tools
            tool_proxy: ToolProxy for unavailable tools
        """
        self._local_invoker = local_invoker
        self._tool_proxy = tool_proxy

    async def invoke(
        self,
        tool_name: str,
        params: dict[str, Any],
        step_id: str | None = None,
        execution_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Invoke a tool, proxying to CP if unavailable locally.

        Args:
            tool_name: Name of the tool
            params: Tool parameters
            step_id: Optional step ID for logging
            execution_id: Optional execution ID for logging
            timeout_seconds: Optional timeout

        Returns:
            Tool invocation result
        """
        return await self._tool_proxy.invoke_tool(
            tool_name=tool_name,
            args=params,
            local_invoker=self._local_invoker,
            timeout=timeout_seconds,
        )
