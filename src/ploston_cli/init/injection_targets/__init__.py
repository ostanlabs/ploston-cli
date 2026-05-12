"""Injection targets plugin system for multi-agent MCP config injection.

Provides InjectionTarget base class, ConfigAdapter protocol, and a
TARGET_REGISTRY dispatch table. Adding a new agent is "subclass + register".

See: MULTI_AGENT_BOOTSTRAP_EXPANSION_W1_SPEC.md (M-084, DEC-198).
"""

from __future__ import annotations

from .base import ConfigAdapter, InjectionTarget
from .registry import TARGET_REGISTRY

__all__ = [
    "ConfigAdapter",
    "InjectionTarget",
    "TARGET_REGISTRY",
]
