"""Init command - Import MCP configurations from Claude Desktop and Cursor.

Implements the `ploston init --import` command per PLOSTON_INIT_IMPORT_SPEC.md.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import click

from ploston_cli.client import PlostClient, PlostClientError
from ploston_cli.init import (
    ConfigDetector,
    ServerSelector,
    generate_runner_token,
    inject_ploston_into_config,
    merge_configs,
    write_env_file,
)

if TYPE_CHECKING:
    from ploston_cli.init.detector import DetectedConfig, ServerInfo

DEFAULT_CP_URL = "http://localhost:8080"
DEFAULT_RUNNER_NAME = "local"


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
    default=None,
    help=f"Control Plane URL (default: {DEFAULT_CP_URL})",
)
@click.option(
    "--inject/--no-inject",
    default=False,
    help="Inject Ploston into source config (comments out imported servers)",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Import all servers without prompting",
)
@click.option(
    "--runner-name",
    default=DEFAULT_RUNNER_NAME,
    help=f"Name for the local runner (default: {DEFAULT_RUNNER_NAME})",
)
def init_command(
    do_import: bool,
    source: str,
    cp_url: str | None,
    inject: bool,
    non_interactive: bool,
    runner_name: str,
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

    # Run the async import flow
    asyncio.run(
        _run_import_flow(
            source=source,
            cp_url=cp_url or DEFAULT_CP_URL,
            inject=inject,
            non_interactive=non_interactive,
            runner_name=runner_name,
        )
    )


async def _run_import_flow(
    source: str,
    cp_url: str,
    inject: bool,
    non_interactive: bool,
    runner_name: str,
) -> None:
    """Execute the full init --import flow."""
    click.echo("\n🚀 Ploston Init - Import MCP Configuration\n")

    # Step 1: Check CP connectivity
    cp_url = await _ensure_cp_connectivity(cp_url, non_interactive)
    if not cp_url:
        sys.exit(1)

    # Step 2: Detect MCP configurations
    config_detector = ConfigDetector()
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
    server_infos = config_detector.build_server_infos(servers)
    if non_interactive:
        selected_names = selector.select_all(server_infos)
        click.echo(f"\n📦 Importing all {len(selected_names)} servers (non-interactive mode).\n")
    else:
        click.echo()
        selected_names = selector.prompt_selection(server_infos)
        click.echo(f"\n📦 {len(selected_names)} servers selected for import\n")

    if not selected_names:
        click.echo("No servers selected. Exiting.")
        sys.exit(0)

    # Continue with the rest of the flow
    await _complete_import_flow(cp_url, found, servers, selected_names, runner_name, inject)


async def _ensure_cp_connectivity(cp_url: str, non_interactive: bool) -> str | None:
    """Ensure CP is reachable, prompting for URL if needed."""
    click.echo(f"🔗 Checking Control Plane connectivity ({cp_url})...")

    async with PlostClient(cp_url) as client:
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
    click.echo("  [3] Run 'ploston bootstrap' to set up CP (placeholder - not yet implemented)")
    click.echo("  [q] Quit")
    click.echo()

    while True:
        choice = click.prompt("Select option", type=str, default="2")

        if choice == "q":
            return None

        if choice == "1":
            new_url = click.prompt("Enter CP URL", default=cp_url)
            async with PlostClient(new_url) as client:
                result = await client.check_cp_connectivity()
            if result.connected:
                click.echo(f"  ✓ Connected to {new_url}")
                return new_url
            click.echo(f"  ❌ Still cannot connect: {result.error}")
            continue

        if choice == "2":
            click.echo("  Waiting for CP to be available...")
            click.pause("  Press Enter when CP is running...")
            async with PlostClient(cp_url) as client:
                result = await client.check_cp_connectivity()
            if result.connected:
                click.echo(f"  ✓ Connected to {cp_url}")
                return cp_url
            click.echo(f"  ❌ Still cannot connect: {result.error}")
            continue

        if choice == "3":
            click.echo()
            click.echo("  ⚠️  PLACEHOLDER: 'ploston bootstrap' is not yet implemented.")
            click.echo("  Please start the Control Plane manually using docker-compose or k8s.")
            click.echo()
            click.pause("  Press Enter when CP is running...")
            async with PlostClient(cp_url) as client:
                result = await client.check_cp_connectivity()
            if result.connected:
                click.echo(f"  ✓ Connected to {cp_url}")
                return cp_url
            click.echo(f"  ❌ Still cannot connect: {result.error}")
            continue

        click.echo("  Invalid option. Please select 1, 2, 3, or q.")


async def _complete_import_flow(
    cp_url: str,
    detected_configs: list[DetectedConfig],
    servers: dict[str, ServerInfo],
    selected_names: list[str],
    runner_name: str,
    inject: bool,
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
            if secret_detector.is_secret(var_name, value):
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
                k: f"${{{k}}}" if secret_detector.is_secret(k, v) else v
                for k, v in server_info.env.items()
            }
        mcp_servers[name] = mcp_entry

    try:
        async with PlostClient(cp_url) as client:
            await client.push_runner_config(
                runner_name=runner_name,
                mcp_servers=mcp_servers,
                token=runner_token,
            )
        click.echo("  ✓ Configuration pushed successfully")
    except PlostClientError as e:
        click.echo(f"  ❌ Failed to push configuration: {e.message}", err=True)
        sys.exit(1)

    # Step 6: Optionally inject into source config
    if inject:
        click.echo("\n🔧 Injecting Ploston into source configurations...")
        for detected in detected_configs:
            if detected.found and detected.path:
                try:
                    inject_ploston_into_config(
                        config_path=detected.path,
                        imported_servers=list(selected_servers.keys()),
                        cp_url=cp_url,
                    )
                    label = "Claude Desktop" if detected.source == "claude_desktop" else "Cursor"
                    click.echo(f"  ✓ Updated {label} config ({detected.path})")
                except Exception as e:
                    click.echo(f"  ⚠️  Failed to update {detected.path}: {e}")

    # Step 7: Print summary
    click.echo("\n" + "=" * 60)
    click.echo("✅ Import Complete!")
    click.echo("=" * 60)
    click.echo()
    click.echo(f"  Runner name: {runner_name}")
    click.echo(f"  Servers imported: {len(selected_names)}")
    click.echo(f"  Secrets stored: {env_file}")
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Start the local runner:")
    click.echo(
        f"     ploston runner start --cp {cp_url.replace('http', 'ws')}/runner --token <token> --name {runner_name}"
    )
    click.echo()
    click.echo("  2. Or view the runner token:")
    click.echo(f"     cat {env_file} | grep PLOSTON_RUNNER_TOKEN")
    click.echo()
