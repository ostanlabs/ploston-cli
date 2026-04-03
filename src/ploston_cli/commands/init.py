"""Init command - Import MCP configurations from Claude Desktop and Cursor.

Implements the `ploston init --import` command per PLOSTON_INIT_IMPORT_SPEC.md.
--inject behaviour amended per INIT_IMPORT_INJECT_AMENDMENT.md (DEC-141).
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

import click

from ploston_cli.client import PlostClient, PlostClientError
from ploston_cli.init import (
    ConfigDetector,
    ServerSelector,
    generate_runner_token,
    merge_configs,
    write_env_file,
)
from ploston_cli.init.detector import ALL_INJECT_TARGETS
from ploston_cli.init.injector import (
    SOURCE_LABELS,
    default_runner_name,
    run_injection,
)

if TYPE_CHECKING:
    from ploston_cli.init.detector import DetectedConfig, ServerInfo

# Environment variable to override config base path (for testing)
ENV_CONFIG_BASE_PATH = "PLOSTON_CONFIG_BASE_PATH"


def _get_default_cp_url() -> str:
    """Get default CP URL from config (env var or config file)."""
    from ploston_cli.config import load_config

    return load_config().server


@click.command("init")
@click.option(
    "--import",
    "do_import",
    is_flag=True,
    help="Import from Claude Desktop or Cursor config",
)
@click.option(
    "--source",
    type=click.Choice(["claude", "cursor", "auto"]),
    default="auto",
    help="Config source to import from",
)
@click.option(
    "--cp-url",
    envvar="PLOSTON_SERVER",
    default=None,
    help="Control Plane URL (default: from PLOSTON_SERVER env or config)",
)
@click.option(
    "--inject/--no-inject",
    default=False,
    help="Inject Ploston into source config (replaces imported servers with bridge entries)",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Import all servers without prompting",
)
@click.option(
    "--runner-name",
    default=None,
    help=(
        "Name for the local runner (default: machine hostname). "
        "Used in --runner args of generated bridge entries."
    ),
)
@click.option(
    "--inject-target",
    "inject_targets",
    multiple=True,
    type=click.Choice(ALL_INJECT_TARGETS),
    help="Inject into specific config target(s). Repeatable. Default: interactive selection.",
)
def init_command(
    do_import: bool,
    source: str,
    cp_url: str | None,
    inject: bool,
    non_interactive: bool,
    runner_name: str | None,
    inject_targets: tuple[str, ...],
) -> None:
    """Initialize Ploston configuration.

    Use --import to import MCP configurations from Claude Desktop or Cursor.

    \b
    Examples:
      ploston init --import                    # Auto-detect and import
      ploston init --import --source claude    # Import from Claude Desktop only
      ploston init --import --inject           # Import and modify source config
      ploston init --import --non-interactive  # Import all without prompting
    """
    if not do_import:
        click.echo("Usage: ploston init --import [OPTIONS]")
        click.echo()
        click.echo("Use --import to import MCP configurations from Claude Desktop or Cursor.")
        click.echo("Run 'ploston init --help' for more options.")
        return

    # If --inject-target is supplied, implicitly enable --inject
    if inject_targets:
        inject = True

    # Run the async import flow
    asyncio.run(
        _run_import_flow(
            source=source,
            cp_url=cp_url or _get_default_cp_url(),
            inject=inject,
            non_interactive=non_interactive,
            runner_name=runner_name,  # None → default_runner_name() applied at inject time
            inject_targets=list(inject_targets) or None,
        )
    )


async def _run_import_flow(
    source: str,
    cp_url: str,
    inject: bool,
    non_interactive: bool,
    runner_name: str | None,
    inject_targets: list[str] | None = None,
) -> None:
    """Execute the full init --import flow."""
    click.echo("\n🚀 Ploston Init - Import MCP Configuration\n")

    # Step 1: Check CP connectivity
    cp_url = await _ensure_cp_connectivity(cp_url, non_interactive)
    if not cp_url:
        sys.exit(1)

    # Step 2: Detect MCP configurations
    # Allow overriding config base path via environment variable (for testing)
    config_base_path = os.environ.get(ENV_CONFIG_BASE_PATH)
    config_detector = ConfigDetector(config_base_path=config_base_path)
    selector = ServerSelector()

    click.echo("📂 Scanning for MCP configurations...")
    if source == "auto":
        detected = config_detector.detect_all()
    else:
        source_key = "claude_desktop" if source == "claude" else "cursor"
        detected = [config_detector.detect_source(source_key)]  # type: ignore

    found = [d for d in detected if d.found]
    if not found:
        click.echo("  ❌ No MCP configurations found.")
        click.echo("  Make sure Claude Desktop or Cursor is installed and configured.")
        sys.exit(1)

    for d in found:
        label = "Claude Desktop" if d.source == "claude_desktop" else "Cursor"
        click.echo(f"  ✓ Found: {label} ({d.path})")
        click.echo(f"    {d.server_count} servers configured")

    # Merge if multiple sources
    if len(found) > 1:
        servers = merge_configs(found)
        click.echo(f"\n{len(servers)} unique servers found (merged).\n")
    else:
        servers = found[0].servers

    if not servers:
        click.echo("  No servers to import.")
        sys.exit(1)

    # Step 3: Select servers to import
    # servers is a dict[str, ServerInfo] - convert to list for selector
    server_list = list(servers.values())
    if non_interactive:
        selected_names = selector.select_all(server_list)
        click.echo(f"\n📦 Importing all {len(selected_names)} servers (non-interactive mode).\n")
    else:
        click.echo()
        selected_names = await selector.prompt_selection(server_list)
        click.echo(f"\n📦 {len(selected_names)} servers selected for import\n")

    if not selected_names:
        click.echo("No servers selected. Exiting.")
        sys.exit(0)

    # Continue with the rest of the flow
    await _complete_import_flow(
        cp_url,
        found,
        servers,
        selected_names,
        runner_name,
        inject,
        inject_targets=inject_targets,
    )


async def _ensure_cp_connectivity(cp_url: str, non_interactive: bool) -> str | None:
    """Ensure CP is reachable, prompting for URL if needed."""
    click.echo(f"🔗 Checking Control Plane connectivity ({cp_url})...")

    # Use a shorter timeout for connectivity check (5 seconds)
    async with PlostClient(cp_url, timeout=5.0) as client:
        result = await client.check_cp_connectivity()

    if result.connected:
        click.echo(f"  ✓ Connected to {cp_url}")
        if result.version:
            click.echo(f"    Version: {result.version}")
        return cp_url

    # CP not reachable
    click.echo(f"  ❌ Cannot connect to Control Plane at {cp_url}")
    click.echo(f"    Error: {result.error}")
    click.echo()

    if non_interactive:
        click.echo("  In non-interactive mode, cannot prompt for CP URL.")
        click.echo("  Please ensure CP is running and use --cp-url to specify the URL.")
        return None

    # Offer options
    click.echo("Options:")
    click.echo("  [1] Enter a different CP URL")
    click.echo("  [2] Start CP manually and press Enter to retry")
    click.echo("  [3] Run 'ploston bootstrap' to set up CP")
    click.echo("  [q] Quit")
    click.echo()

    while True:
        choice = click.prompt("Select option", type=str, default="2")

        if choice == "q":
            return None

        if choice == "1":
            new_url = click.prompt("Enter CP URL", default=cp_url)
            async with PlostClient(new_url, timeout=5.0) as client:
                result = await client.check_cp_connectivity()
            if result.connected:
                click.echo(f"  ✓ Connected to {new_url}")
                return new_url
            click.echo(f"  ❌ Still cannot connect: {result.error}")
            continue

        if choice == "2":
            click.echo("  Waiting for CP to be available...")
            click.pause("  Press Enter when CP is running...")
            async with PlostClient(cp_url, timeout=5.0) as client:
                result = await client.check_cp_connectivity()
            if result.connected:
                click.echo(f"  ✓ Connected to {cp_url}")
                return cp_url
            click.echo(f"  ❌ Still cannot connect: {result.error}")
            continue

        if choice == "3":
            click.echo()
            click.echo("  🚀 Running 'ploston bootstrap'...")
            click.echo()
            import subprocess

            # Run bootstrap with --no-import to avoid circular dependency
            result = subprocess.run(
                ["ploston", "bootstrap", "--no-import"],
                capture_output=False,
            )
            if result.returncode != 0:
                click.echo("  ❌ Bootstrap failed. Please check the output above.")
                continue
            # After bootstrap, check connectivity
            async with PlostClient(cp_url, timeout=5.0) as client:
                conn_result = await client.check_cp_connectivity()
            if conn_result.connected:
                click.echo(f"  ✓ Connected to {cp_url}")
                return cp_url
            click.echo(f"  ❌ Still cannot connect: {conn_result.error}")
            continue

        click.echo("  Invalid option. Please select 1, 2, 3, or q.")


async def _complete_import_flow(
    cp_url: str,
    detected_configs: list[DetectedConfig],
    servers: dict[str, ServerInfo],
    selected_names: list[str],
    runner_name: str | None,
    inject: bool,
    inject_targets: list[str] | None = None,
) -> None:
    """Complete the import flow after server selection."""
    from ploston_core.config.secrets import SecretDetector

    secret_detector = SecretDetector()

    # Step 4: Detect secrets and generate .env
    click.echo("🔐 Detecting secrets...")
    env_vars: dict[str, str] = {}
    selected_servers = {name: servers[name] for name in selected_names}

    for name, server_info in selected_servers.items():
        for var_name, value in server_info.env.items():
            if secret_detector.detect(var_name, value):
                env_vars[var_name] = value
                click.echo(f"  ✓ {var_name} (from {name})")

    runner_token = generate_runner_token()
    env_file = write_env_file(runner_token, env_vars)
    click.echo(f"\n✓ Secrets written to {env_file}")

    # Step 5: Push config to CP
    click.echo(f"\n📤 Pushing configuration to Control Plane ({cp_url})...")

    # Convert servers to MCP format for CP
    mcp_servers: dict = {}
    for name, server_info in selected_servers.items():
        mcp_entry: dict = {
            "command": server_info.command or "",
            "args": server_info.args,
            "transport": server_info.transport,
        }
        if server_info.env:
            # Replace actual values with ${VAR} references for secrets
            mcp_entry["env"] = {
                k: f"${{{k}}}" if secret_detector.detect(k, v) else v
                for k, v in server_info.env.items()
            }
        mcp_servers[name] = mcp_entry

    # Resolve effective runner name before CP push so it matches bridge entries
    effective_runner_name = runner_name if runner_name is not None else default_runner_name()

    try:
        async with PlostClient(cp_url) as client:
            await client.push_runner_config(
                runner_name=effective_runner_name,
                mcp_servers=mcp_servers,
                token=runner_token,
                merge=True,  # Additive: preserve previously imported servers
            )
        click.echo("  ✓ Configuration pushed successfully")
    except PlostClientError as e:
        click.echo(f"  ❌ Failed to push configuration: {e.message}", err=True)
        sys.exit(1)

    # Step 6: Optionally inject into source config
    if inject:
        click.echo("\n🔧 Injecting Ploston into source configurations...")
        results = run_injection(
            detected_configs=detected_configs,
            imported_servers=list(selected_servers.keys()),
            cp_url=cp_url,
            runner_name=effective_runner_name,
            targets=inject_targets,
        )
        for source_type, path, error in results:
            label = SOURCE_LABELS.get(source_type, source_type)
            if error:
                click.echo(f"  ⚠️  Failed to update {path}: {error}")
            else:
                click.echo(f"  ✓ Updated {label} config ({path})")

    # Step 7: Print summary
    click.echo("\n" + "=" * 60)
    click.echo("✅ Import Complete!")
    click.echo("=" * 60)
    click.echo()
    click.echo(f"  Runner name: {effective_runner_name}")
    click.echo(f"  Servers imported: {len(selected_names)}")
    click.echo(f"  Secrets stored: {env_file}")
    click.echo()

    if inject:
        click.echo("✓ Claude Desktop config updated with drop-in bridge entries.")
        click.echo()
        click.echo("  Each original MCP server is now proxied through Ploston:")
        for name in selected_names:
            click.echo(
                f"    {name:<16}→  ploston bridge --expose {name} --runner {effective_runner_name}"
            )
        click.echo()
        click.echo("  A new 'ploston' entry exposes your Ploston workflows.")
        click.echo()
        click.echo("  Next steps:")
        click.echo("    1. Start the local runner:")
        click.echo("         ploston runner start --daemon")
        click.echo("    2. Restart Claude Desktop to apply config changes.")
        click.echo()
        click.echo("  To restore original config:")
        click.echo("    Swap 'mcpServers' with '_ploston_imported' in your Claude Desktop config.")
    else:
        click.echo("Next steps:")
        click.echo("  1. Start the local runner:")
        click.echo(
            f"     ploston runner start --daemon --cp {cp_url.replace('http', 'ws')}/api/v1/runner/ws"
            f" --token {runner_token} --name {effective_runner_name}"
        )
        click.echo()
