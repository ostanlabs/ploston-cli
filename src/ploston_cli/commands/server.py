"""ploston server — MCP server management commands.

See: DEC169-175_ROUTING_TAGS_CLI_SPEC.md §6 (T-768)
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import click

from ..client import PlostClient, PlostClientError
from ..completion import complete_server_names
from ..init.detector import ALL_INJECT_TARGETS
from ..init.injector import SOURCE_LABELS, default_runner_name, run_injection


def _get_server_url(ctx: click.Context) -> str:
    from ..main import get_server_url

    return get_server_url(ctx)


def _get_insecure(ctx: click.Context) -> bool:
    return ctx.obj.get("insecure", False)


@click.group("server")
def server_group() -> None:
    """Manage MCP servers registered on the Control Plane."""


@server_group.command("list")
@click.pass_context
def server_list(ctx: click.Context) -> None:
    """List registered MCP servers on the CP.

    Displays name, status, source and tool count.
    """
    server_url = _get_server_url(ctx)
    insecure = _get_insecure(ctx)

    async def _list() -> list[dict[str, Any]]:
        async with PlostClient(server_url, insecure=insecure) as client:
            tools = await client.list_tools()
        # Group by server
        servers: dict[str, dict[str, Any]] = {}
        for t in tools:
            srv = t.get("server") or t.get("source", "unknown")
            if srv not in servers:
                servers[srv] = {"name": srv, "tool_count": 0, "source": t.get("source", "?")}
            servers[srv]["tool_count"] += 1
        return list(servers.values())

    try:
        result = asyncio.run(_list())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    if ctx.obj.get("json_output"):
        click.echo(json.dumps(result, indent=2))
    else:
        if not result:
            click.echo("No servers registered.")
            return
        click.echo(f"Registered servers ({len(result)}):\n")
        for s in result:
            click.echo(
                f"  {s['name']:<20s}  source={s.get('source', '?'):<10s}  tools={s['tool_count']}"
            )


@server_group.command("add")
@click.argument("name", required=False)
@click.option("--detect", is_flag=True, help="Auto-detect from Claude/Cursor configs")
@click.option("--command", "cmd", help="Server command (manual mode)")
@click.option("--args", "cmd_args", help="Server args as JSON array (manual mode)")
@click.option("--env", "env_vars", multiple=True, help="Environment var KEY=VAL (repeatable)")
@click.option("--inject", is_flag=True, help="Inject into agent configs after adding")
@click.option(
    "--inject-target",
    "inject_targets",
    multiple=True,
    type=click.Choice(ALL_INJECT_TARGETS),
    help="Inject into specific config target(s). Repeatable. Implies --inject.",
)
@click.pass_context
def server_add(
    ctx: click.Context,
    name: str | None,
    detect: bool,
    cmd: str | None,
    cmd_args: str | None,
    env_vars: tuple[str, ...],
    inject: bool,
    inject_targets: tuple[str, ...],
) -> None:
    """Add an MCP server to the Control Plane.

    \b
    Detection mode (reuses config scanner):
      ploston server add --detect

    \b
    Manual mode:
      ploston server add fetch --command npx --args '["@mcp/fetch"]'
      ploston server add fetch --command npx --args '["@mcp/fetch"]' --inject
      ploston server add fetch --command npx ... --inject-target cursor
    """
    if inject_targets:
        inject = True

    if detect:
        _server_add_detect(ctx, inject=inject, inject_targets=list(inject_targets) or None)
        return

    if not name or not cmd:
        raise click.UsageError("Provide <name> --command <cmd>, or use --detect.")

    # Parse args
    args_list: list[str] = []
    if cmd_args:
        try:
            args_list = json.loads(cmd_args)
        except json.JSONDecodeError:
            raise click.BadParameter(f"--args must be valid JSON array, got: {cmd_args}")

    # Parse env
    env: dict[str, str] = {}
    for ev in env_vars:
        if "=" not in ev:
            raise click.BadParameter(f"--env must be KEY=VAL, got: {ev}")
        k, v = ev.split("=", 1)
        env[k] = v

    server_config = {"command": cmd, "args": args_list}
    if env:
        server_config["env"] = env

    server_url = _get_server_url(ctx)
    insecure = _get_insecure(ctx)

    async def _push() -> dict[str, Any]:
        async with PlostClient(server_url, insecure=insecure) as client:
            # Get runner token (needed for push_runner_config)
            from ..init.injector import default_runner_name

            runner_name = default_runner_name()
            try:
                token = await client.get_runner_token(runner_name)
            except PlostClientError:
                token = "auto"  # Will be created if needed
            return await client.push_runner_config(
                runner_name=runner_name,
                mcp_servers={name: server_config},
                token=token,
                merge=True,
            )

    try:
        asyncio.run(_push())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    click.echo(f"✓ Server '{name}' added.")

    if inject:
        _run_inject_after_add(
            server_url=server_url,
            inject_targets=list(inject_targets) or None,
        )


def _run_inject_after_add(
    server_url: str,
    inject_targets: list[str] | None = None,
) -> None:
    """Run injection into agent configs after server add."""
    import os

    from ..init import ConfigDetector

    config_base_path = os.environ.get("PLOSTON_CONFIG_BASE_PATH")
    config_detector = ConfigDetector(config_base_path=config_base_path)
    detected = config_detector.detect_all()

    available = [d for d in detected if d.found and d.path]
    if not available:
        click.echo("  No agent configs detected — skipping injection.")
        return

    # Get list of all registered servers from CP for injection
    async def _get_servers() -> list[str]:
        async with PlostClient(server_url, insecure=False, timeout=5.0) as client:
            tools = await client.list_tools()
        servers: set[str] = set()
        for t in tools:
            srv = t.get("server") or t.get("source")
            if srv and srv not in ("native", "workflow"):
                servers.add(srv)
        return sorted(servers)

    try:
        imported_servers = asyncio.run(_get_servers())
    except PlostClientError:
        click.echo("  ⚠️  Could not fetch server list for injection.")
        return

    runner_name = default_runner_name()
    click.echo("🔧 Injecting into agent configurations...")
    results = run_injection(
        detected_configs=detected,
        imported_servers=imported_servers,
        cp_url=server_url,
        runner_name=runner_name,
        targets=inject_targets,
    )
    for source_type, path, error in results:
        label = SOURCE_LABELS.get(source_type, source_type)
        if error:
            click.echo(f"  ⚠️  {label}: {error}")
        else:
            click.echo(f"  ✓ {label} ({path})")


def _server_add_detect(
    ctx: click.Context,
    inject: bool = False,
    inject_targets: list[str] | None = None,
) -> None:
    """Detection mode for server add — reuses ConfigDetector."""
    from ..init import ConfigDetector, ServerSelector, merge_configs

    config_detector = ConfigDetector()
    selector = ServerSelector()

    found = config_detector.detect_all()
    servers = merge_configs(found)

    if not servers:
        click.echo("No MCP servers detected in Claude Desktop or Cursor configs.")
        return

    # Fetch already-registered server names from the CP to exclude them
    server_url = _get_server_url(ctx)
    insecure = _get_insecure(ctx)
    already_registered: set[str] = set()

    async def _get_existing() -> set[str]:
        try:
            async with PlostClient(server_url, insecure=insecure) as client:
                runner_name = default_runner_name()
                # Use the config API — same endpoint push_runner_config reads from
                runner_cfg = await client._request("GET", f"/api/v1/config/runners/{runner_name}")
                return set(runner_cfg.get("mcp_servers", {}).keys())
        except (PlostClientError, Exception):
            return set()

    already_registered = asyncio.run(_get_existing())

    # Filter out already-imported servers
    new_servers = {k: v for k, v in servers.items() if k not in already_registered}
    if not new_servers:
        click.echo("All detected servers are already registered. Nothing to add.")
        return

    if already_registered:
        skipped = sorted(already_registered & set(servers.keys()))
        if skipped:
            click.echo(f"Skipping already registered: {', '.join(skipped)}")

    server_list = list(new_servers.values())

    async def _select() -> list[str]:
        return await selector.prompt_selection(server_list)

    selected = asyncio.run(_select())
    if not selected:
        click.echo("No servers selected.")
        return

    async def _push() -> None:
        async with PlostClient(server_url, insecure=insecure) as client:
            runner_name = default_runner_name()
            mcp_servers = {}
            for name in selected:
                info = new_servers[name]
                entry: dict[str, Any] = {}
                if info.command:
                    entry["command"] = info.command
                if info.args:
                    entry["args"] = info.args
                if info.env:
                    entry["env"] = info.env
                mcp_servers[name] = entry

            try:
                token = await client.get_runner_token(runner_name)
            except PlostClientError:
                token = "auto"
            await client.push_runner_config(
                runner_name=runner_name,
                mcp_servers=mcp_servers,
                token=token,
                merge=True,
            )

    try:
        asyncio.run(_push())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    click.echo(f"✓ {len(selected)} server(s) added: {', '.join(selected)}")

    if inject:
        server_url = _get_server_url(ctx)
        _run_inject_after_add(
            server_url=server_url,
            inject_targets=inject_targets,
        )


@server_group.command("remove")
@click.argument("name", shell_complete=complete_server_names)
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
@click.pass_context
def server_remove(ctx: click.Context, name: str, force: bool) -> None:
    """Remove an MCP server from the Control Plane."""
    if not force:
        click.confirm(f"Remove server '{name}'?", abort=True)

    server_url = _get_server_url(ctx)
    insecure = _get_insecure(ctx)

    async def _remove() -> None:
        async with PlostClient(server_url, insecure=insecure) as client:
            from ..init.injector import default_runner_name

            runner_name = default_runner_name()
            # Read existing runner config, remove the server, push back
            try:
                existing = await client._request("GET", f"/api/v1/config/runners/{runner_name}")
            except PlostClientError:
                raise PlostClientError(404, f"Runner '{runner_name}' not found")
            existing_servers = existing.get("mcp_servers", {})
            if name not in existing_servers:
                raise PlostClientError(404, f"Server '{name}' not found on runner '{runner_name}'")
            del existing_servers[name]
            token = existing.get("token", "auto")
            await client.push_runner_config(
                runner_name=runner_name,
                mcp_servers=existing_servers,
                token=token,
                merge=False,
            )

    try:
        asyncio.run(_remove())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    click.echo(f"✓ Server '{name}' removed.")
