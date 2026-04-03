"""ploston inject — Standalone config injection command.

Re-runs injection using current Ploston config without re-importing anything.
Useful after installing a new MCP-capable agent or after manual config edits.

See: DEC169-175_ROUTING_TAGS_CLI_SPEC.md §7.4 (T-769)
"""

from __future__ import annotations

import asyncio
import os
import sys

import click

from ..client import PlostClient, PlostClientError
from ..init import ConfigDetector
from ..init.detector import ALL_INJECT_TARGETS
from ..init.injector import SOURCE_LABELS, default_runner_name, run_injection

# Environment variable to override config base path (for testing)
ENV_CONFIG_BASE_PATH = "PLOSTON_CONFIG_BASE_PATH"


@click.command("inject")
@click.option(
    "--inject-target",
    "inject_targets",
    multiple=True,
    type=click.Choice(ALL_INJECT_TARGETS),
    help="Inject into specific config target(s). Repeatable. Default: all detected.",
)
@click.pass_context
def inject_command(ctx: click.Context, inject_targets: tuple[str, ...]) -> None:
    """Re-run Ploston config injection without re-importing servers.

    Detects available agent configs (Claude Desktop, Cursor, Claude Code) and
    injects Ploston bridge entries. Use after installing a new MCP-capable
    agent or after manual config edits.

    \b
    Examples:
      ploston inject                                       # Inject into all detected
      ploston inject --inject-target cursor                # Only Cursor
      ploston inject --inject-target claude_code_global    # Only Claude Code global
    """
    from ..main import get_server_url

    cp_url = get_server_url(ctx)
    insecure = ctx.obj.get("insecure", False)

    # Detect configs
    config_base_path = os.environ.get(ENV_CONFIG_BASE_PATH)
    config_detector = ConfigDetector(config_base_path=config_base_path)
    detected = config_detector.detect_all()

    available = [d for d in detected if d.found and d.path]
    if not available:
        click.echo("No agent configs detected. Nothing to inject into.")
        return

    # Fetch list of registered servers from CP
    async def _get_servers() -> list[str]:
        async with PlostClient(cp_url, insecure=insecure, timeout=5.0) as client:
            tools = await client.list_tools()
        # Extract unique server names
        servers: set[str] = set()
        for t in tools:
            srv = t.get("server") or t.get("source")
            if srv and srv not in ("native", "workflow"):
                servers.add(srv)
        return sorted(servers)

    try:
        imported_servers = asyncio.run(_get_servers())
    except PlostClientError as e:
        click.echo(f"Error connecting to CP: {e.message}", err=True)
        sys.exit(1)

    runner_name = default_runner_name()
    targets = list(inject_targets) if inject_targets else None

    click.echo("🔧 Injecting Ploston into agent configurations...")
    results = run_injection(
        detected_configs=detected,
        imported_servers=imported_servers,
        cp_url=cp_url,
        runner_name=runner_name,
        targets=targets,
    )

    if not results:
        click.echo("No configs were injected (none matched the specified targets).")
        return

    for source_type, path, error in results:
        label = SOURCE_LABELS.get(source_type, source_type)
        if error:
            click.echo(f"  ⚠️  {label}: {error}")
        else:
            click.echo(f"  ✓ {label} ({path})")

    click.echo(f"\n✅ Done. {sum(1 for _, _, e in results if e is None)} config(s) updated.")
