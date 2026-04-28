"""Shared modules for ploston-cli.

This module provides shared functionality used across all CLI modes:
- Bridge (agent proxy)
- Runner (local execution daemon)
- CLI (management commands)
"""

from .auth import auth_headers, get_token
from .logging import configure_logging
from .paths import (
    CA_DIR,
    INSPECTOR_LOG_FILE,
    INSPECTOR_PID_FILE,
    INSPECTOR_STATE_FILE,
    LOG_DIR,
    PID_FILE,
    PLOSTON_DIR,
    RUNNER_PID_FILE,
    TOKENS_DIR,
    ensure_dirs,
)

__all__ = [
    # Paths
    "PLOSTON_DIR",
    "PID_FILE",
    "RUNNER_PID_FILE",
    "INSPECTOR_PID_FILE",
    "INSPECTOR_LOG_FILE",
    "INSPECTOR_STATE_FILE",
    "LOG_DIR",
    "TOKENS_DIR",
    "CA_DIR",
    "ensure_dirs",
    # Auth
    "get_token",
    "auth_headers",
    # Logging
    "configure_logging",
]
