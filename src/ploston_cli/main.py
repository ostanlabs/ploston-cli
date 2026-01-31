"""CLI main entry point.

Ploston CLI - A thin HTTP client for Ploston servers.
All operations are delegated to the server via REST API.
"""

import asyncio
import json
import sys
from typing import Any

import click

from .client import PlostClient, PlostClientError
from .config import DEFAULT_SERVER, load_config
from .utils import parse_inputs

__version__ = "1.0.0"


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
@click.pass_context
def cli(
    ctx: click.Context, server: str | None, verbose: int, quiet: bool, json_output: bool
) -> None:
    """Ploston CLI - Command-line interface for Ploston servers.

    Connect to a Ploston server to manage workflows and tools.

    \b
    Server URL precedence:
      1. --server flag
      2. PLOSTON_SERVER environment variable
      3. ~/.ploston/config.yaml
      4. Default: http://localhost:8080
    """
    ctx.ensure_object(dict)
    ctx.obj["server"] = server
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    ctx.obj["json_output"] = json_output


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

    async def _run() -> None:
        # Parse inputs
        input_dict = parse_inputs(inputs, input_file)

        async with PlostClient(server_url) as client:
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

    async def _version() -> None:
        async with PlostClient(server_url) as client:
            try:
                caps = await client.get_capabilities()
                if ctx.obj["json_output"]:
                    click.echo(
                        json.dumps(
                            {
                                "cli_version": __version__,
                                "server_version": caps.get("version", "unknown"),
                                "server_tier": caps.get("tier", "unknown"),
                                "server_url": server_url,
                            },
                            indent=2,
                        )
                    )
                else:
                    click.echo(f"Ploston CLI version {__version__}")
                    click.echo(f"Server: {server_url}")
                    click.echo(f"Server version: {caps.get('version', 'unknown')}")
                    click.echo(f"Server tier: {caps.get('tier', 'unknown')}")
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
        if "inputs" in workflow_data:
            if not isinstance(workflow_data["inputs"], list):
                errors.append("'inputs' must be a list")
            else:
                for i, inp in enumerate(workflow_data["inputs"]):
                    if not isinstance(inp, dict):
                        errors.append(f"inputs[{i}]: Input must be a mapping")
                        continue
                    if "name" not in inp:
                        errors.append(f"inputs[{i}]: Missing required field 'name'")

        # Validate outputs if present
        if "outputs" in workflow_data:
            if not isinstance(workflow_data["outputs"], list):
                errors.append("'outputs' must be a list")

    # Check tools on server if requested
    if check_tools and not errors:
        server_url = get_server_url(ctx)

        async def _check_tools() -> list[str]:
            tool_errors: list[str] = []
            async with PlostClient(server_url) as client:
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

    async def _list() -> list[dict[str, Any]]:
        async with PlostClient(server_url) as client:
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

    async def _show() -> dict[str, Any] | None:
        async with PlostClient(server_url) as client:
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

    # Validate section if provided
    if section and section not in VALID_SECTIONS:
        click.echo(f"Error: Unknown section '{section}'", err=True)
        click.echo(f"\nValid sections:\n  {', '.join(VALID_SECTIONS)}")
        sys.exit(1)

    async def _get_config() -> dict[str, Any]:
        async with PlostClient(server_url) as client:
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

    async def _list() -> list[dict[str, Any]]:
        async with PlostClient(server_url) as client:
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

    async def _show() -> dict[str, Any] | None:
        async with PlostClient(server_url) as client:
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

    async def _refresh() -> dict[str, Any]:
        async with PlostClient(server_url) as client:
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
    """Create a new runner and get its connection token.

    The token is only shown once. Save it to connect the runner.

    Example:
        ploston runner create marc-laptop
    """
    server_url = get_server_url(ctx)

    async def _create() -> dict[str, Any]:
        async with PlostClient(server_url) as client:
            return await client.create_runner(name)

    try:
        result = asyncio.run(_create())
    except PlostClientError as e:
        click.echo(f"Error: {e.message}", err=True)
        sys.exit(1)

    if ctx.obj["json_output"]:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Runner '{name}' created successfully!")
        click.echo()
        click.echo("To connect this runner, run the following command on the target machine:")
        click.echo()
        click.echo(f"  {result.get('install_command', 'N/A')}")
        click.echo()
        click.echo("⚠️  Save this command - the token cannot be retrieved again.")


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

    async def _list() -> list[dict[str, Any]]:
        async with PlostClient(server_url) as client:
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

    async def _show() -> dict[str, Any] | None:
        async with PlostClient(server_url) as client:
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

    async def _delete() -> dict[str, Any]:
        async with PlostClient(server_url) as client:
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


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
