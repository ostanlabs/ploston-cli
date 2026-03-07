"""Ploston CLI - Command-line interface for Ploston."""

# Version is stamped into _version.py by `make install-cli-from-source`.
# Falls back to importlib.metadata (for PyPI installs) or a dev sentinel.
try:
    from ._version import __version__
except ImportError:
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("ploston-cli")
    except PackageNotFoundError:
        __version__ = "0.0.0+local"

from .main import main

__all__ = ["main", "__version__"]
