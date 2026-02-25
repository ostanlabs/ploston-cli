"""Config receiver for handling config/push messages from Control Plane.

Handles:
- Parsing MCP configurations pushed from CP
- Environment variable resolution
- Config validation
- Triggering MCP initialization
"""

import logging
import os
import re
from typing import Any

from .types import MCPConfig, RunnerMCPConfig

logger = logging.getLogger(__name__)

# Pattern for environment variable references: ${VAR_NAME}
ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigReceiver:
    """Receives and processes MCP configurations from Control Plane.

    Handles config/push messages, resolves environment variables,
    and provides parsed configurations for MCP initialization.
    """

    def __init__(self, on_config_received: Any | None = None):
        """Initialize config receiver.

        Args:
            on_config_received: Optional callback when new config is received.
                               Signature: async def callback(config: RunnerMCPConfig) -> None
        """
        self._current_config: RunnerMCPConfig | None = None
        self._on_config_received = on_config_received

    @property
    def current_config(self) -> RunnerMCPConfig | None:
        """Current MCP configuration."""
        return self._current_config

    def _resolve_env_vars(self, value: str) -> str:
        """Resolve environment variable references in a string.

        Supports ${VAR_NAME} syntax. If the variable is not set,
        the reference is left as-is (for debugging).

        Args:
            value: String potentially containing env var references

        Returns:
            String with env vars resolved
        """

        def replace_var(match: re.Match[str]) -> str:
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is not None:
                return env_value
            logger.warning(f"Environment variable {var_name} not set")
            return match.group(0)  # Return original if not found

        return ENV_VAR_PATTERN.sub(replace_var, value)

    def _resolve_env_dict(self, env: dict[str, str]) -> dict[str, str]:
        """Resolve environment variables in an env dict.

        Args:
            env: Dict of environment variables

        Returns:
            Dict with env var references resolved
        """
        return {key: self._resolve_env_vars(value) for key, value in env.items()}

    def _parse_mcp_config(self, name: str, config_dict: dict[str, Any]) -> MCPConfig:
        """Parse a single MCP configuration.

        Args:
            name: MCP server name
            config_dict: Raw config dict from CP

        Returns:
            Parsed MCPConfig
        """
        # Resolve env vars in the env dict
        env = config_dict.get("env", {})
        resolved_env = self._resolve_env_dict(env)

        return MCPConfig(
            name=name,
            command=config_dict.get("command", ""),
            args=config_dict.get("args", []),
            env=resolved_env,
            url=config_dict.get("url"),
        )

    async def handle_config_push(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle config/push message from Control Plane.

        Args:
            params: Message params containing MCP configs

        Returns:
            Response dict with status
        """
        logger.info("Received config push from Control Plane")

        try:
            mcps_raw = params.get("mcps", {})
            mcps: dict[str, MCPConfig] = {}

            for name, config_dict in mcps_raw.items():
                try:
                    mcp_config = self._parse_mcp_config(name, config_dict)
                    mcps[name] = mcp_config
                    logger.debug(f"Parsed MCP config: {name}")
                except Exception as e:
                    logger.error(f"Failed to parse MCP config '{name}': {e}")

            self._current_config = RunnerMCPConfig(mcps=mcps)

            logger.info(f"Received configuration for {len(mcps)} MCPs: {list(mcps.keys())}")

            # Trigger callback if set
            if self._on_config_received:
                await self._on_config_received(self._current_config)

            return {"status": "ok", "mcps_received": len(mcps)}

        except Exception as e:
            logger.error(f"Failed to process config push: {e}")
            return {"status": "error", "message": str(e)}

    def get_mcp_config(self, name: str) -> MCPConfig | None:
        """Get configuration for a specific MCP.

        Args:
            name: MCP server name

        Returns:
            MCPConfig if found, None otherwise
        """
        if not self._current_config:
            return None
        return self._current_config.mcps.get(name)

    def list_mcp_names(self) -> list[str]:
        """List all configured MCP names.

        Returns:
            List of MCP server names
        """
        if not self._current_config:
            return []
        return list(self._current_config.mcps.keys())
