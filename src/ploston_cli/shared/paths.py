"""Path management for ploston-cli.

Manages ~/.ploston/ directory structure for all CLI modes.
"""

from pathlib import Path

# Base directory for all ploston data
PLOSTON_DIR = Path.home() / ".ploston"

# Runner PID file location
PID_FILE = PLOSTON_DIR / "runner.pid"

# Log directory (same as base for simplicity)
LOG_DIR = PLOSTON_DIR

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


def get_log_file(name: str = "runner") -> Path:
    """Get path to a log file.

    Args:
        name: Log file name (without extension)

    Returns:
        Path to the log file
    """
    return LOG_DIR / f"{name}.log"


def get_token_file(source: str) -> Path:
    """Get path to a token file.

    Args:
        source: Token source name (e.g., "bridge", "runner", "cli")

    Returns:
        Path to the token file
    """
    return TOKENS_DIR / f"{source}.token"
