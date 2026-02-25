"""Logging configuration for ploston-cli.

Configures structlog with JSON output for daemon mode, human-readable for
foreground/CLI mode.
"""

import logging
import sys
from pathlib import Path

import structlog


def configure_logging(
    level: str = "warning",
    log_file: str | Path | None = None,
    json_output: bool = False,
) -> None:
    """Configure logging for the application.

    Called once on startup. Configures both standard logging and structlog.

    Args:
        level: Log level (debug, info, warning, error, critical)
        log_file: Optional path to log file (for daemon mode)
        json_output: If True, output JSON format (for daemon mode)

    Usage:
        Daemon mode: configure_logging(level, log_file=LOG_FILE, json_output=True)
        Foreground mode: configure_logging(level, json_output=False)
        CLI mode: configure_logging(level) (stderr, human-readable)
    """
    log_level = getattr(logging, level.upper(), logging.WARNING)

    # Configure standard logging
    handlers: list[logging.Handler] = []

    if log_file:
        file_handler = logging.FileHandler(str(log_file))
        file_handler.setLevel(log_level)
        handlers.append(file_handler)
    else:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setLevel(log_level)
        handlers.append(stream_handler)

    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        format="%(message)s",
        force=True,
    )

    # Configure structlog
    processors: list[structlog.types.Processor] = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)
