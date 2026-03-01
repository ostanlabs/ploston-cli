"""CLI main entry point.

Ploston CLI - A thin HTTP client for Ploston servers.
All operations are delegated to the server via REST API.
"""

import asyncio
import json
import sys
from typing import Any

import click

# Import version from package metadata (set in __init__.py)
from . import __version__
from .client import PlostClient, PlostClientError
from .commands.bootstrap import bootstrap
from .commands.bridge import bridge_command
from .commands.init import init_command
from .config import DEFAULT_SERVER, load_config
from .utils import parse_inputs


def get_server_url(ctx: click.Context) -> str:
    """Get server URL from context, env, or config file.

    Precedence: CLI flag > env var > config file > default
    """
    # CLI flag takes precedence
    if ctx.obj.get("server"):
        return ctx.obj["server"]

    # Load from config (handles env var and config file)
    cli_config = load_config()
    return cli_config.server


def get_insecure(ctx: click.Context) -> bool:
    """Get insecure flag from context."""
    return ctx.obj.get("insecure", False)


@click.group()
@click.option(
    "-s",
    "--server",
    envvar="PLOSTON_SERVER",
    help=f"Server URL (default: {DEFAULT_SERVER})",
)
@click.option("-v", "--verbose", count=True, help="Increase verbosity")
@click.option("-q", "--quiet", is_flag=True, help="Suppress output")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option(
    "-k",
    "--insecure",
    is_flag=True,
    envvar="PLOSTON_INSECURE",
    help="Skip SSL certificate verification (like curl -k)",
)
@click.pass_context
def cli(
    ctx: click.Context,
    server: str | None,
    verbose: int,
    quiet: bool,
    json_output: bool,
    insecure: bool,
) -> None:
    """Ploston CLI - Command-line interface for Ploston servers.

    Connect to a Ploston server to manage workflows and tools.

    \b
    Server URL precedence:
      1. --server flag
      2. PLOSTON_SERVER environment variable
      3. ~/.ploston/config.yaml
      4. Default: http://localhost:8082
    """
    ctx.ensure_object(dict)
    ctx.obj["server"] = server
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    ctx.obj["json_output"] = json_output
    ctx.obj["insecure"] = insecure


# Register commands
cli.add_command(bootstrap)
cli.add_command(bridge_command)
cli.add_command(init_command)


@cli.command()
@click.argument("workflow")
@click.option("-i", "--input", "inputs", multiple=True, help="Input KEY=VALUE")
@click.option("--input-file", type=click.Path(exists=True), help="Inputs file")
@click.option("-t", "--timeout", type=int, help="Timeout in seconds")
@click.pass_context
def run(
    ctx: click.Context,
    workflow: str,
    inputs: tuple[str, ...],
    input_file: str | None,
    timeout: int | None,
) -> None:
    """Execute a workflow on the Ploston server."""
    server_url = get_server_url(ctx)
    insecure = get_insecure(ctx)

    async def _run() -> None:
        # Parse inputs
        input_dict = parse_inputs(inputs, input_file)

        async with PlostClient(server_url, insecure=insecure) as client:
            try:
                result = await client.execute_workflow(workflow, input_dict, timeout)

                # Output result
                if ctx.obj["json_output"]:
                    click.echo(json.dumps(result, indent=2))
                else:
                    click.echo(f"Status: {result.get('status', 'unknown')}")
                    click.echo(f"Execution ID: {result.get('execution_id', 'N/A')}")
                    outputs = result.get("outputs", {})
                    if outputs:
                        click.echo("Outputs:")
                        for key, value in outputs.items():
                            click.echo(f"  {key}: {value}")
                    error = result.get("error")
                    if error:
                        click.echo(f"Error: {error}", err=True)

            except PlostClientError as e:
                click.echo(f"Error: {e.message}", err=True)
                sys.exit(1)

    asyncio.run(_run())


@cli.command()
@click.pass_context
def version(ctx: click.Context) -> None:
    """Show version information."""
    server_url = get_server_url(ctx)
    insecure = get_insecure(ctx)

    async def _version() -> None:
        async with PlostClient(server_url, insecure=insecure) as client:
            try:
                # First check if server is reachable via health endpoint
                health = await client.health()
                server_available = health.get("status") == "ok"

                # Try to get capabilities (may not exist on all server versions)
                caps = {}
                try:
                    caps = await client.get_capabilities()
                except PlostClientError:
                    pass  # Capabilities endpoint may not exist

                if ctx.obj["json_output"]:
                    click.echo(
                        json.dumps(
                            {
                                "cli_version": __version__,
                                "server_version": caps.get("version", "unknown"),
                                "server_tier": caps.get("tier", "unknown"),
                                "server_url": server_url,
                                "server_status": "available" if server_available else "unavailable",
                            },
                            indent=2,
                        )
                    )
                else:
                    click.echo(f"Ploston CLI version {__version__}")
                    click.echo(f"Server: {server_url}")
                    if caps:
                        click.echo(f"Server version: {caps.get('version', 'unknown')}")
                        click.echo(f"Server tier: {caps.get('tier', 'unknown')}")
                    else:
                        click.echo("Server status: available")
            except PlostClientError:
                # Server not available, just show CLI version
                if ctx.obj["json_output"]:
                    click.echo(
                        json.dumps(
                            {
                                "cli_version": __version__,
                                "server_version": None,
                                "server_tier": None,
                                "server_url": server_url,
                                "server_status": "unavailable",
                            },
                            indent=2,
                        )
                    )
                else:
                    click.echo(f"Ploston CLI version {__version__}")
                    click.echo(f"Server: {server_url} (unavailable)")

    asyncio.run(_version())


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--strict", is_flag=True, help="Treat warnings as errors")
@click.option(
    "--check-tools",
    is_flag=True,
    help="Verify tools exist on server (requires server connection)",
)
@click.pass_context
def validate(ctx: click.Context, file: str, strict: bool, check_tools: bool) -> None:
    """Validate a workflow YAML file.

    Performs local YAML validation. Use --check-tools to verify
    that referenced tools exist on the server.
    """
    from pathlib import Path

    import yaml as pyyaml

    from .formatters import print_validation_result

    # Read file
    file_path = Path(file)
    try:
        yaml_content = file_path.read_text()
    except Exception as e:
        click.echo(f"Error reading file: {e}", err=True)
        sys.exit(1)

    errors: list[str] = []
    warnings: list[str] = []

    # Parse YAML
    try:
        workflow_data = pyyaml.safe_load(yaml_content)
    except pyyaml.YAMLError as e:
        errors.append(f"YAML parse error: {e}")
        if ctx.obj["json_output"]:
            click.echo(json.dumps({"valid": False, "errors": errors, "warnings": []}, indent=2))
        else:
            print_validation_result(str(file), errors, warnings)
        sys.exit(1)

    # Basic structure validation (local, no server needed)
    if not isinstance(workflow_data, dict):
        errors.append("Workflow must be a YAML mapping")
    else:
        # Check required fields
        if "name" not in workflow_data:
            errors.append("Missing required field: name")
        if "version" not in workflow_data:
            errors.append("Missing required field: version")
        if "steps" not in workflow_data:
            errors.append("Missing required field: steps")
        elif not isinstance(workflow_data.get("steps"), list):
            errors.append("'steps' must be a list")
        elif len(workflow_data.get("steps", [])) == 0:
            errors.append("Workflow must have at least one step")
        else:
            # Validate each step
            for i, step in enumerate(workflow_data["steps"]):
                if not isinstance(step, dict):
                    errors.append(f"steps[{i}]: Step must be a mapping")
                    continue
                if "id" not in step:
                    errors.append(f"steps[{i}]: Missing required field 'id'")
                if "tool" not in step and "code" not in step:
                    errors.append(f"steps[{i}]: Step must have either 'tool' or 'code'")

        # Validate inputs if present
        # Supported formats:
        # - "name"  (string - simple required input)
        # - name: default  (dict with name as key, default value)
        # - name: {type: ..., ...}  (dict with name as key, full definition)
        if "inputs" in workflow_data:
            if not isinstance(workflow_data["inputs"], list):
                errors.append("'inputs' must be a list")
            else:
                for i, inp in enumerate(workflow_data["inputs"]):
                    if isinstance(inp, str):
                        # Simple string format: required input
                        continue
                    elif isinstance(inp, dict):
                        # Dict format: key is the input name
                        if len(inp) == 0:
                            errors.append(f"inputs[{i}]: Empty input definition")
                        # Valid: {name: default} or {name: {type: ..., ...}}
                    else:
                        errors.append(f"inputs[{i}]: Input must be a string or mapping")

        # Validate outputs if present
        if "outputs" in workflow_data:
            if not isinstance(workflow_data["outputs"], list):
                errors.append("'outputs' must be a list")

    # Check tools on server if requested
    if check_tools and not errors:
        server_url = get_server_url(ctx)
        insecure = get_insecure(ctx)

        async def _check_tools() -> list[str]:
            tool_errors: list[str] = []
            async with PlostClient(server_url, insecure=insecure) as client:
                try:
                    tools_list = await client.list_tools()
                    tool_names = {t["name"] for t in tools_list}

                    for i, step in enumerate(workflow_data.get("steps", [])):
                        tool_name = step.get("tool")
                        if tool_name and tool_name not in tool_names:
                            tool_errors.append(
                                f"steps[{i}]: Tool '{tool_name}' not found on server"
                            )
                except PlostClientError as e:
                    tool_errors.append(f"Cannot connect to server for tool check: {e.message}")
            return tool_errors

        tool_check_errors = asyncio.run(_check_tools())
        errors.extend(tool_check_errors)

    # Output
    if ctx.obj["json_output"]:
        click.echo(
            json.dumps(
                {"valid": len(errors) == 0, "errors": errors, "warnings": warnings},
                indent=2,
            )
        )
    else:
        print_validation_result(str(file), errors, warnings)

    # Exit code
    if errors or (strict and warnings):
        sys.exit(1)


@cli.group()
def workflows() -> None:
    """Manage workflows on the server."""
    pass


@workflows.command("list")
@click.pass_context
def workflows_list(ctx: click.Context) -> None:
    """List registered workflows on the server."""
    server_url = get_server_url(ctx)
    insecure = get_insecure(ctx)

    async def _list() -> list[dict[str, Any]]:
        async with PlostClient(server_url, insecure=insecure) as client:
            return await client.list_workflows()

    try:
        workflows_result = asyncio.run(_list())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    if ctx.obj["json_output"]:
        click.echo(json.dumps(workflows_result, indent=2))
    else:
        click.echo(f"Total workflows: {len(workflows_result)}")
        for w in workflows_result:
            name = w.get("name", "unknown")
            version = w.get("version", "?")
            description = w.get("description", "")
            click.echo(f"  - {name} (v{version}): {description}")


@workflows.command("show")
@click.argument("name")
@click.pass_context
def workflows_show(ctx: click.Context, name: str) -> None:
    """Show workflow details."""
    from .formatters import print_workflow_detail_dict

    server_url = get_server_url(ctx)
    insecure = get_insecure(ctx)

    async def _show() -> dict[str, Any] | None:
        async with PlostClient(server_url, insecure=insecure) as client:
            try:
                return await client.get_workflow(name)
            except PlostClientError as e:
                if e.status_code == 404:
                    return None
                raise

    try:
        workflow = asyncio.run(_show())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    if not workflow:
        click.echo(f"Error: Workflow '{name}' not found", err=True)
        sys.exit(1)

    if ctx.obj["json_output"]:
        click.echo(json.dumps(workflow, indent=2))
    else:
        print_workflow_detail_dict(workflow)


# Valid server config sections
VALID_SECTIONS = [
    "server",
    "mcp",
    "tools",
    "workflows",
    "execution",
    "python_exec",
    "logging",
    "plugins",
    "security",
    "telemetry",
]


@cli.group()
def config() -> None:
    """Manage CLI and server configuration."""
    pass


@config.command("show")
@click.option("--section", help="Show specific section of server config")
@click.option("--local", is_flag=True, help="Show local CLI config instead of server config")
@click.pass_context
def config_show(ctx: click.Context, section: str | None, local: bool) -> None:
    """Show configuration.

    By default shows server configuration. Use --local to show CLI config.
    """
    from .config import get_config_path, load_config
    from .formatters import print_config_yaml

    if local:
        # Show local CLI config
        cli_config = load_config()
        config_path = get_config_path()

        data = {
            "server": cli_config.server,
            "timeout": cli_config.timeout,
            "output_format": cli_config.output_format,
        }

        if ctx.obj["json_output"]:
            click.echo(
                json.dumps(
                    {
                        "config_path": str(config_path),
                        "values": data,
                        "sources": cli_config._sources,
                    },
                    indent=2,
                )
            )
        else:
            click.echo("Ploston CLI Configuration")
            click.echo(f"Config file: {config_path}")
            click.echo()
            for key, value in data.items():
                source = cli_config.get_source(key)
                click.echo(f"  {key}: {value} (from {source})")
        return

    # Show server config
    server_url = get_server_url(ctx)
    insecure = get_insecure(ctx)

    # Validate section if provided
    if section and section not in VALID_SECTIONS:
        click.echo(f"Error: Unknown section '{section}'", err=True)
        click.echo(f"\nValid sections:\n  {', '.join(VALID_SECTIONS)}")
        sys.exit(1)

    async def _get_config() -> dict[str, Any]:
        async with PlostClient(server_url, insecure=insecure) as client:
            return await client.get_config(section)

    try:
        data = asyncio.run(_get_config())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    if ctx.obj["json_output"]:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        if not section:
            click.echo("Ploston Server Configuration")
            click.echo(f"Server: {server_url}\n")
        print_config_yaml(data, section)


@config.command("set")
@click.argument("key", type=click.Choice(["server", "timeout", "output_format"]))
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a CLI configuration value.

    Saves to ~/.ploston/config.yaml
    """
    from .config import save_config

    # Convert value to appropriate type
    if key == "timeout":
        try:
            value = int(value)  # type: ignore
        except ValueError:
            click.echo("Error: timeout must be an integer", err=True)
            sys.exit(1)

    save_config(key, value)
    click.echo(f"Set {key} = {value}")


@config.command("unset")
@click.argument("key", type=click.Choice(["server", "timeout", "output_format"]))
def config_unset(key: str) -> None:
    """Remove a CLI configuration value.

    The default value will be used instead.
    """
    from .config import unset_config

    if unset_config(key):
        click.echo(f"Removed {key} from config")
    else:
        click.echo(f"{key} was not set in config")


@config.command("diff")
@click.pass_context
def config_diff(ctx: click.Context) -> None:
    """Show diff between current config and staged changes.

    Only meaningful in configuration mode. Shows what changes will be
    applied when 'config_done' is called.
    """
    server_url = get_server_url(ctx)
    insecure = get_insecure(ctx)

    async def _get_diff() -> dict[str, Any]:
        async with PlostClient(server_url, insecure=insecure) as client:
            return await client.get_config_diff()

    try:
        result = asyncio.run(_get_diff())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        raise SystemExit(1)

    if not result.get("in_config_mode"):
        click.echo("Not in configuration mode. No staged changes to show.")
        click.echo("Use 'config_begin' to enter configuration mode.")
        return

    if not result.get("has_changes"):
        click.echo("No staged changes.")
        return

    # Print the diff
    diff = result.get("diff", "")
    if diff:
        click.echo("Staged configuration changes:")
        click.echo()
        # Color the diff output
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                click.secho(line, fg="green")
            elif line.startswith("-") and not line.startswith("---"):
                click.secho(line, fg="red")
            elif line.startswith("@@"):
                click.secho(line, fg="cyan")
            else:
                click.echo(line)


@cli.group()
def tools() -> None:
    """Manage tools on the server."""
    pass


@tools.command("list")
@click.option("--source", type=click.Choice(["mcp", "system"]), help="Filter by source")
@click.option("--server", help="Filter by MCP server name")
@click.option("--status", type=click.Choice(["available", "unavailable"]), help="Filter by status")
@click.pass_context
def tools_list(
    ctx: click.Context, source: str | None, server: str | None, status: str | None
) -> None:
    """List available tools on the server."""
    from .formatters import print_tools_list_dict

    server_url = get_server_url(ctx)
    insecure = get_insecure(ctx)

    async def _list() -> list[dict[str, Any]]:
        async with PlostClient(server_url, insecure=insecure) as client:
            return await client.list_tools(source=source, server=server, status=status)

    try:
        tools_result = asyncio.run(_list())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    if ctx.obj["json_output"]:
        click.echo(json.dumps(tools_result, indent=2))
    else:
        print_tools_list_dict(tools_result)


@tools.command("show")
@click.argument("name")
@click.pass_context
def tools_show(ctx: click.Context, name: str) -> None:
    """Show tool details."""
    from .formatters import print_tool_detail_dict

    server_url = get_server_url(ctx)
    insecure = get_insecure(ctx)

    async def _show() -> dict[str, Any] | None:
        async with PlostClient(server_url, insecure=insecure) as client:
            try:
                return await client.get_tool(name)
            except PlostClientError as e:
                if e.status_code == 404:
                    return None
                raise

    try:
        tool = asyncio.run(_show())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    if not tool:
        click.echo(f"Error: Tool '{name}' not found", err=True)
        sys.exit(1)

    if ctx.obj["json_output"]:
        click.echo(json.dumps(tool, indent=2))
    else:
        print_tool_detail_dict(tool)


@tools.command("refresh")
@click.option("--server", "server_name", help="Refresh specific server only")
@click.pass_context
def tools_refresh(ctx: click.Context, server_name: str | None) -> None:
    """Refresh tool schemas from MCP servers."""
    from .formatters import print_refresh_result_dict

    server_url = get_server_url(ctx)
    insecure = get_insecure(ctx)

    async def _refresh() -> dict[str, Any]:
        async with PlostClient(server_url, insecure=insecure) as client:
            return await client.refresh_tools(server=server_name)

    click.echo("Refreshing tools...")
    try:
        result = asyncio.run(_refresh())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    if ctx.obj["json_output"]:
        click.echo(json.dumps(result, indent=2))
    else:
        print_refresh_result_dict(result)


# =============================================================================
# Runner Commands
# =============================================================================


@cli.group()
def runner() -> None:
    """Manage runners (local tool execution agents)."""
    pass


@runner.command("create")
@click.argument("name")
@click.pass_context
def runner_create(ctx: click.Context, name: str) -> None:
    """Create a new runner - DEPRECATED.

    Runners must be defined in the config file under the 'runners' section.

    Example config (ael-config.yaml):

        runners:
          my-runner:
            mcp_servers:
              filesystem:
                command: npx
                args: ["@mcp/filesystem", "/home"]

    After defining the runner in config and running config_done,
    use 'ploston runner get-token <name>' to get the connection token.
    """
    click.echo("Error: Runner creation via CLI is no longer supported.", err=True)
    click.echo()
    click.echo("Runners must be defined in the config file (ael-config.yaml):")
    click.echo()
    click.echo("  runners:")
    click.echo(f"    {name}:")
    click.echo("      mcp_servers:")
    click.echo("        filesystem:")
    click.echo("          command: npx")
    click.echo('          args: ["@mcp/filesystem", "/home"]')
    click.echo()
    click.echo("After adding the runner to config and running config_done,")
    click.echo(f"use 'ploston runner get-token {name}' to get the connection token.")
    sys.exit(1)


@runner.command("list")
@click.option(
    "--status",
    type=click.Choice(["connected", "disconnected"]),
    help="Filter by status",
)
@click.pass_context
def runner_list(ctx: click.Context, status: str | None) -> None:
    """List all registered runners."""
    server_url = get_server_url(ctx)
    insecure = get_insecure(ctx)

    async def _list() -> list[dict[str, Any]]:
        async with PlostClient(server_url, insecure=insecure) as client:
            return await client.list_runners(status=status)

    try:
        runners = asyncio.run(_list())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    if ctx.obj["json_output"]:
        click.echo(json.dumps({"runners": runners, "total": len(runners)}, indent=2))
    else:
        if not runners:
            click.echo("No runners registered.")
            click.echo("\nCreate one with: ploston runner create <name>")
            return

        click.echo(f"Total runners: {len(runners)}")
        click.echo()
        for r in runners:
            status_icon = "🟢" if r.get("status") == "connected" else "⚪"
            name = r.get("name", "unknown")
            tool_count = r.get("tool_count", 0)
            last_seen = r.get("last_seen", "never")
            click.echo(f"  {status_icon} {name}")
            click.echo(f"      Tools: {tool_count}, Last seen: {last_seen}")


@runner.command("show")
@click.argument("name")
@click.pass_context
def runner_show(ctx: click.Context, name: str) -> None:
    """Show runner details."""
    server_url = get_server_url(ctx)
    insecure = get_insecure(ctx)

    async def _show() -> dict[str, Any] | None:
        async with PlostClient(server_url, insecure=insecure) as client:
            try:
                return await client.get_runner(name)
            except PlostClientError as e:
                if e.status_code == 404:
                    return None
                raise

    try:
        runner_detail = asyncio.run(_show())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    if not runner_detail:
        click.echo(f"Error: Runner '{name}' not found", err=True)
        sys.exit(1)

    if ctx.obj["json_output"]:
        click.echo(json.dumps(runner_detail, indent=2))
    else:
        status_icon = "🟢" if runner_detail.get("status") == "connected" else "⚪"
        click.echo(f"Runner: {runner_detail.get('name')}")
        click.echo(f"  ID: {runner_detail.get('id')}")
        click.echo(f"  Status: {status_icon} {runner_detail.get('status')}")
        click.echo(f"  Created: {runner_detail.get('created_at')}")
        click.echo(f"  Last seen: {runner_detail.get('last_seen', 'never')}")

        tools = runner_detail.get("available_tools", [])
        if tools:
            click.echo(f"  Tools ({len(tools)}):")
            for tool in tools[:10]:  # Show first 10
                click.echo(f"    - {tool}")
            if len(tools) > 10:
                click.echo(f"    ... and {len(tools) - 10} more")
        else:
            click.echo("  Tools: none")


@runner.command("delete")
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
@click.pass_context
def runner_delete(ctx: click.Context, name: str, force: bool) -> None:
    """Delete a runner."""
    if not force:
        click.confirm(f"Delete runner '{name}'?", abort=True)

    server_url = get_server_url(ctx)
    insecure = get_insecure(ctx)

    async def _delete() -> dict[str, Any]:
        async with PlostClient(server_url, insecure=insecure) as client:
            return await client.delete_runner(name)

    try:
        result = asyncio.run(_delete())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    if ctx.obj["json_output"]:
        click.echo(json.dumps(result, indent=2))
    else:
        if result.get("deleted"):
            click.echo(f"Runner '{name}' deleted.")
        else:
            click.echo(f"Failed to delete runner '{name}'.")


@runner.command("get-token")
@click.argument("name")
@click.pass_context
def runner_get_token(ctx: click.Context, name: str) -> None:
    """Get a runner's connection token.

    Note: Tokens are not stored in retrievable form for security.
    Use 'regenerate-token' to get a new token.
    """
    click.echo("Error: Tokens are not stored in retrievable form for security.", err=True)
    click.echo()
    click.echo(f"To get a new token, use: ploston runner regenerate-token {name}")
    click.echo("Note: This will invalidate the current token.")
    sys.exit(1)


@runner.command("regenerate-token")
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
@click.pass_context
def runner_regenerate_token(ctx: click.Context, name: str, force: bool) -> None:
    """Regenerate a runner's authentication token.

    This invalidates the old token and generates a new one.
    The runner will need to reconnect with the new token.
    """
    if not force:
        click.confirm(
            f"Regenerate token for runner '{name}'? This will disconnect the runner.",
            abort=True,
        )

    server_url = get_server_url(ctx)
    insecure = get_insecure(ctx)

    async def _regenerate() -> dict[str, Any]:
        async with PlostClient(server_url, insecure=insecure) as client:
            return await client.regenerate_runner_token(name)

    try:
        result = asyncio.run(_regenerate())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    if ctx.obj["json_output"]:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Token regenerated for runner '{name}'")
        click.echo()
        click.echo("New token (save this, it won't be shown again):")
        click.echo(f"  {result.get('token')}")
        click.echo()
        click.echo("Install command:")
        click.echo(f"  {result.get('install_command')}")


# =============================================================================
# Local Runner Daemon Commands
# =============================================================================


@runner.command("start")
@click.option(
    "--cp",
    envvar="PLOSTON_RUNNER_CP",
    required=True,
    help="CP WebSocket URL (wss://...)",
)
@click.option(
    "--token",
    envvar="PLOSTON_RUNNER_TOKEN",
    required=True,
    help="Runner authentication token",
)
@click.option(
    "--name",
    envvar="PLOSTON_RUNNER_NAME",
    required=True,
    help="Runner name (unique identifier)",
)
@click.option(
    "--daemon/--foreground",
    default=True,
    help="Run as daemon (default) or in foreground",
)
@click.option(
    "--log-level",
    default="info",
    type=click.Choice(["debug", "info", "warning", "error"]),
    help="Log level",
)
def runner_start(cp: str, token: str, name: str, daemon: bool, log_level: str) -> None:
    """Start the local runner daemon.

    The runner connects to the Control Plane via WebSocket and executes
    tools locally using MCP servers defined in the CP configuration.

    \b
    Examples:
      ploston runner start --daemon --cp wss://ploston:8443/runner --token xxx --name my-laptop
      ploston runner start --foreground --cp wss://ploston:8443/runner --token xxx --name my-laptop
    """
    from .runner.command import run_runner
    from .runner.daemon import start_daemon
    from .shared.paths import ensure_dirs

    ensure_dirs()

    if daemon:
        start_daemon(
            run_runner,
            cp=cp,
            token=token,
            name=name,
            log_level=log_level,
        )
    else:
        # Foreground mode - run directly
        from .shared.logging import configure_logging

        configure_logging(level=log_level, json_output=False)
        run_runner(cp=cp, token=token, name=name)


@runner.command("stop")
def runner_stop() -> None:
    """Stop the local runner daemon."""
    from .runner.daemon import stop_daemon

    stop_daemon()


@runner.command("status")
def runner_status() -> None:
    """Check local runner daemon status."""
    from .runner.daemon import is_running

    alive, pid = is_running()
    if alive:
        # Also check health endpoint
        import httpx

        try:
            resp = httpx.get("http://localhost:9876/health", timeout=2)
            health = resp.json()
            click.echo(f"Runner: running (PID {pid})")
            click.echo(f"  Name: {health.get('name', 'unknown')}")
            click.echo(f"  CP: {health.get('cp_connected', 'unknown')}")
            click.echo(f"  Tools: {health.get('available_tools', 0)} available")
        except Exception:
            click.echo(f"Runner: running (PID {pid}) but health check failed")
    else:
        click.echo("Runner: not running")


@runner.command("logs")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--lines", "-n", default=50, help="Number of lines to show")
def runner_logs(follow: bool, lines: int) -> None:
    """View local runner daemon logs."""
    import subprocess

    from .shared.paths import LOG_DIR

    log_file = LOG_DIR / "runner.log"

    if not log_file.exists():
        click.echo("No log file found.")
        return

    if follow:
        subprocess.run(["tail", "-f", str(log_file)])
    else:
        subprocess.run(["tail", "-n", str(lines), str(log_file)])


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
