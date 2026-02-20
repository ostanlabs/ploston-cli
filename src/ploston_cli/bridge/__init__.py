"""Bridge module - MCP stdio-to-HTTP transport.

Provides the `ploston bridge` command for connecting MCP clients
(Claude Desktop, Cursor, etc.) to Ploston Control Plane.
"""

from .errors import BridgeError, map_connection_error, map_http_error
from .health import HealthMonitor
from .lifecycle import BridgeLifecycle
from .proxy import BridgeProxy, BridgeProxyError
from .server import BridgeServer
from .stream import StreamHandler

__all__ = [
    "BridgeError",
    "BridgeProxyError",
    "BridgeProxy",
    "BridgeServer",
    "HealthMonitor",
    "BridgeLifecycle",
    "StreamHandler",
    "map_http_error",
    "map_connection_error",
]
