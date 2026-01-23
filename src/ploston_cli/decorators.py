"""Tier-aware command decorators.

This module provides decorators for checking feature availability
and showing upgrade prompts for enterprise features.
"""

from functools import wraps
from typing import Callable

import click
from rich.console import Console

from .capabilities import ServerCapabilities

console = Console()


def requires_feature(feature: str):
    """Decorator that checks if a feature is available.

    Shows upgrade prompt if feature requires Enterprise.

    Args:
        feature: The feature name to check (e.g., "policy", "patterns").

    Returns:
        Decorated function that checks feature availability.
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            ctx = click.get_current_context()
            capabilities: ServerCapabilities = ctx.obj.get("capabilities")

            if not capabilities:
                console.print("[red]Error:[/red] Not connected to server")
                raise SystemExit(1)

            if not capabilities.is_feature_enabled(feature):
                console.print(
                    f"[red]Error:[/red] {feature.replace('_', ' ').title()} "
                    f"requires Ploston Enterprise.\n"
                )
                console.print("[dim]To upgrade:[/dim]")
                console.print("  pip install ploston-enterprise")
                console.print("  [dim]# or[/dim]")
                console.print("  docker run ghcr.io/ostanlabs/ploston-enterprise")
                console.print("")
                console.print("[dim]Contact:[/dim] sales@ostanlabs.com")
                raise SystemExit(1)

            return await func(*args, **kwargs)

        return wrapper

    return decorator


class EnterpriseCommand(click.Command):
    """Command class that shows [Enterprise] badge in help.

    Use this for commands that require enterprise features.
    """

    def __init__(self, *args, feature: str = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.feature = feature

        # Add [Enterprise] badge to help text
        if self.help:
            self.help = f"[Enterprise] {self.help}"
        else:
            self.help = "[Enterprise]"

    def invoke(self, ctx):
        """Check feature before invoking command."""
        capabilities = ctx.obj.get("capabilities")

        if capabilities and self.feature:
            if not capabilities.is_feature_enabled(self.feature):
                console.print("[red]Error:[/red] This command requires Ploston Enterprise.\n")
                console.print("[dim]To upgrade:[/dim]")
                console.print("  pip install ploston-enterprise")
                console.print("")
                console.print("[dim]Contact:[/dim] sales@ostanlabs.com")
                raise SystemExit(1)

        return super().invoke(ctx)
