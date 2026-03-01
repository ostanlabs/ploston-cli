"""Init command package for importing MCP configurations.

This package provides the `ploston init --import` command which:
1. Detects existing MCP configurations from Claude Desktop and Cursor
2. Lets users interactively select which servers to import
3. Pushes configuration to a running Control Plane
4. Generates a .env file with secrets at ~/.ploston/.env
"""

from .detector import ConfigDetector, DetectedConfig, ServerInfo, merge_configs
from .env_manager import (
    ENV_FILE,
    PLOSTON_DIR,
    EnvEntry,
    EnvFileManager,
    generate_runner_token,
    load_env_file,
    load_env_file_with_sections,
    merge_env_file,
    write_env_file,
    write_env_file_with_sections,
)
from .injector import (
    SourceConfigInjector,
    inject_ploston_into_config,
    is_already_injected,
    list_backups,
    restore_config_from_backup,
)
from .selector import ServerSelector, display_import_summary

__all__ = [
    "ConfigDetector",
    "DetectedConfig",
    "ServerInfo",
    "merge_configs",
    "ServerSelector",
    "display_import_summary",
    "EnvEntry",
    "EnvFileManager",
    "generate_runner_token",
    "write_env_file",
    "write_env_file_with_sections",
    "load_env_file",
    "load_env_file_with_sections",
    "merge_env_file",
    "PLOSTON_DIR",
    "ENV_FILE",
    "SourceConfigInjector",
    "inject_ploston_into_config",
    "restore_config_from_backup",
    "list_backups",
    "is_already_injected",
]
