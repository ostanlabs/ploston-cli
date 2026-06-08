"""Init command - Import MCP configurations from Claude Desktop and Cursor.

Implements the `ploston init --import` command per PLOSTON_INIT_IMPORT_SPEC.md.
--inject behaviour amended per INIT_IMPORT_INJECT_AMENDMENT.md (DEC-141).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from ploston_cli.client import PlostClient, PlostClientError
from ploston_cli.init import (
    ConfigDetector,
    ServerSelector,
    generate_runner_token,
    load_env_file,
    merge_configs,
    write_env_file,
)
from ploston_cli.init.detector import ALL_INJECT_TARGETS
from ploston_cli.init.injector import (
    SOURCE_LABELS,
    default_runner_name,
    run_injection,
)
from ploston_cli.init.target_selector import select_targets

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
@click.option(
    "--no-backup-file",
    is_flag=True,
    default=False,
    help="Skip Layer-2 file backup before injection. Use if you manage config via version control.",
)
def init_command(
    do_import: bool,
    source: str,
    cp_url: str | None,
    inject: bool,
    non_interactive: bool,
    runner_name: str | None,
    inject_targets: tuple[str, ...],
    no_backup_file: bool,
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
            no_backup_file=no_backup_file,
        )
    )


async def _run_import_flow(
    source: str,
    cp_url: str,
    inject: bool,
    non_interactive: bool,
    runner_name: str | None,
    inject_targets: list[str] | None = None,
    no_backup_file: bool = False,
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
        # Surface per-source detail so users can distinguish "file missing" from
        # "file present but unreadable / invalid JSON / permission denied".
        actionable_files_present = False
        for d in detected:
            label = SOURCE_LABELS.get(d.source, d.source)
            path_present = bool(str(d.path)) and d.path.exists()
            if d.error:
                path_str = str(d.path) if str(d.path) else "(no path)"
                click.echo(f"     {label} ({path_str}):")
                click.echo(f"       → {d.error}")
                if path_present:
                    actionable_files_present = True
            elif d.server_count == 0:
                click.echo(f"     {label} ({d.path}):")
                click.echo("       → No MCP servers defined in config")
                actionable_files_present = True
        # Only show the install hint when every source is genuinely absent.
        # If any source file exists but failed to parse or had no servers, the
        # hint is misleading — the per-source detail above is the real guidance.
        if not actionable_files_present:
            click.echo("  Make sure Claude Desktop or Cursor is installed and configured.")
        sys.exit(1)

    # T-1005: Compact grouped detection display
    home = str(Path.home())
    total_sources = len(detected)
    click.echo(f"📂 Detected MCP configurations ({len(found)} of {total_sources} sources):\n")
    for d in found:
        label = SOURCE_LABELS.get(d.source, d.source)
        path_str = str(d.path).replace(str(home), "~") if d.path else "?"
        svr_word = "server" if d.server_count == 1 else "servers"
        click.echo(f"  {label:<24}{path_str}   {d.server_count} {svr_word}")
    # Show per-source errors (always surfaced even when some sources found)
    for d in detected:
        if not d.found and d.error:
            label = SOURCE_LABELS.get(d.source, d.source)
            click.echo(f"  ⚠ {label}: {d.error}")

    # Merge if multiple sources
    if len(found) > 1:
        merge_warnings: list[str] = []
        servers = merge_configs(found, warnings=merge_warnings)
        total_raw = sum(d.server_count for d in found)
        deduped = total_raw - len(servers)
        dedup_note = f" ({deduped} duplicates deduplicated)" if deduped > 0 else ""
        click.echo(f"\n  {len(servers)} unique servers{dedup_note}\n")
        for warn in merge_warnings:
            click.echo(f"  ⚠️  {warn}")
        if merge_warnings:
            click.echo()
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
        non_interactive=non_interactive,
        no_backup_file=no_backup_file,
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
    non_interactive: bool = False,
    no_backup_file: bool = False,
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

    # Preserve existing runner token when re-importing (avoids CP token mismatch)
    existing_env = load_env_file()
    runner_token = existing_env.get("PLOSTON_RUNNER_TOKEN") or generate_runner_token()
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

    # Step 6: Optionally inject into source config (with target picker)
    chosen_targets: list[str] = []
    results: list[tuple[str, object, str | None]] = []
    injection_failed = False
    if inject:
        # Use TargetSelector to determine which targets to inject into
        chosen_targets = select_targets(
            detected_configs=detected_configs,
            selected_server_names=list(selected_servers.keys()),
            non_interactive=non_interactive,
            inject_targets=inject_targets,
        )
        if not chosen_targets:
            click.echo("\n  No targets selected for injection. Skipping.")
        else:
            click.echo("\n🔧 Injecting Ploston into source configurations...")
            results = run_injection(
                detected_configs=detected_configs,
                imported_servers=list(selected_servers.keys()),
                cp_url=cp_url,
                runner_name=effective_runner_name,
                targets=chosen_targets,
                no_backup_file=no_backup_file,
            )
            for source_type, path, error in results:
                label = SOURCE_LABELS.get(source_type, source_type)
                if error:
                    injection_failed = True
                    click.echo(f"  ⚠️  Failed to update {path}: {error}", err=True)
                else:
                    click.echo(f"  ✓ Updated {label} config ({path})")

    # Step 7: Auto-start the runner (same as bootstrap does)
    click.echo("\n🚀 Starting local runner...")
    from ..bootstrap import RunnerAutoStart

    runner_starter = RunnerAutoStart(cp_url)
    runner_running, runner_msg = runner_starter.check_runner_status()
    if runner_running:
        click.echo("  ✓ Runner already running — restarting to pick up new config...")
        # Stop and restart so it picks up the updated MCP config
        import subprocess

        subprocess.run(["ploston", "runner", "stop"], capture_output=True)
        success, msg = runner_starter.start_runner(daemon=True)
        if success:
            click.echo("  ✓ Runner restarted")
        else:
            click.echo(f"  ⚠ Failed to restart runner: {msg}")
    else:
        success, msg = runner_starter.start_runner(daemon=True)
        if success:
            click.echo("  ✓ Runner started")
        else:
            click.echo(f"  ⚠ Failed to start runner: {msg}")
            click.echo("    You can start it manually:")
            click.echo("      ploston runner start --daemon")

    # Step 8: T-1005 structured summary
    click.echo("\n🚀 Setup complete\n")
    click.echo(f"  Imported {len(selected_names)} MCP servers to Ploston")

    if inject and chosen_targets:
        # Collect successfully injected agent names
        injected_labels = [
            SOURCE_LABELS.get(src, src) for src, _path, err in results if err is None
        ]
        if injected_labels:
            agents_str = ", ".join(injected_labels)
            click.echo(f"  Injected Ploston into {len(injected_labels)} agents: {agents_str}")
            click.echo("  ⚠ Restart these agents to pick up the new config")
    click.echo()
    click.echo("  Verify: ploston tools list")
    click.echo("  Roll back: ploston bootstrap rollback")

    # Surface partial injection failure with a non-zero exit code so callers
    # (scripts, CI) don't treat a half-applied injection as success. The
    # summary above still shows which targets succeeded.
    if injection_failed:
        failed_targets = [
            SOURCE_LABELS.get(src, src) for src, _path, err in results if err is not None
        ]
        click.echo(
            f"\n❌ Injection failed for {len(failed_targets)} target(s): "
            f"{', '.join(failed_targets)}",
            err=True,
        )
        sys.exit(1)
