"""Ploston CLI - Command-line interface for Ploston."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ploston-cli")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"  # Fallback for editable installs without metadata

from .main import main

__all__ = ["main", "__version__"]
