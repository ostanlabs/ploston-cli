"""Path management for ploston-cli.

Manages ~/.ploston/ directory structure for all CLI modes.
"""

from pathlib import Path

# Base directory for all ploston data
PLOSTON_DIR = Path.home() / ".ploston"

# Runner daemon PID + log file locations.
# ``PID_FILE`` is the long-standing public name and is preserved as an alias of
# ``RUNNER_PID_FILE`` for backward compatibility (it is also re-exported from
# ``ploston_cli.shared``).
RUNNER_PID_FILE = PLOSTON_DIR / "runner.pid"
PID_FILE = RUNNER_PID_FILE

# Inspector daemon PID + log file locations. ``INSPECTOR_STATE_FILE`` carries
# the bound ``host``/``port`` so ``ploston inspector status`` and
# ``ploston bootstrap status`` can show the listening URL without re-deriving
# it from defaults (which would lie if the user passed ``--port``).
INSPECTOR_PID_FILE = PLOSTON_DIR / "inspector.pid"
INSPECTOR_LOG_FILE = PLOSTON_DIR / "inspector.log"
INSPECTOR_STATE_FILE = PLOSTON_DIR / "inspector.state.json"

# Log directory (same as base for simplicity)
LOG_DIR = PLOSTON_DIR

# MCP server log directory
MCP_LOG_DIR = PLOSTON_DIR / "logs"

# Token storage directory
TOKENS_DIR = PLOSTON_DIR / "tokens"

# CA certificates directory (for mTLS)
CA_DIR = PLOSTON_DIR / "ca"


def ensure_dirs() -> None:
    """Create directory structure if missing.

    Called once on CLI startup. Creates:
    - ~/.ploston/ (mode 0o700 - user-only access)
    - ~/.ploston/tokens/ (mode 0o700)
    - ~/.ploston/ca/ (mode 0o700)

    No wizard, no prompts - silent creation.
    """
    PLOSTON_DIR.mkdir(mode=0o700, exist_ok=True)
    TOKENS_DIR.mkdir(mode=0o700, exist_ok=True)
    CA_DIR.mkdir(mode=0o700, exist_ok=True)
    MCP_LOG_DIR.mkdir(mode=0o700, exist_ok=True)


def get_log_file(name: str = "runner") -> Path:
    """Get path to a log file.

    Args:
        name: Log file name (without extension)

    Returns:
        Path to the log file
    """
    return LOG_DIR / f"{name}.log"


def mcp_log_path(mcp_name: str) -> Path:
    """Return the log file path for a named MCP server.

    Args:
        mcp_name: MCP server name

    Returns:
        Path to the MCP server log file (~/.ploston/logs/<name>.log)
    """
    MCP_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return MCP_LOG_DIR / f"{mcp_name}.log"


def get_token_file(source: str) -> Path:
    """Get path to a token file.

    Args:
        source: Token source name (e.g., "bridge", "runner", "cli")

    Returns:
        Path to the token file
    """
    return TOKENS_DIR / f"{source}.token"
