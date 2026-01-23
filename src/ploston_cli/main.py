"""CLI main entry point."""

import asyncio
import json
import sys
from typing import Any

import click

__version__ = "1.0.0"  # Defined here to avoid circular import

from .application import AELApplication
from .utils import parse_inputs


@click.group()
@click.option("-c", "--config", type=click.Path(), help="Config file path")
@click.option("-v", "--verbose", count=True, help="Increase verbosity")
@click.option("-q", "--quiet", is_flag=True, help="Suppress output")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.pass_context
def cli(ctx: click.Context, config: str, verbose: int, quiet: bool, json_output: bool) -> None:
    """Agent Execution Layer CLI."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    ctx.obj["json_output"] = json_output


@cli.command()
@click.option("--no-watch", is_flag=True, help="Disable hot-reload")
@click.option(
    "--mode",
    type=click.Choice(["configuration", "running"]),
    help="Force startup mode (auto-detect if not specified)",
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http"]),
    default="stdio",
    help="Transport type (default: stdio)",
)
@click.option(
    "--port",
    type=int,
    default=8080,
    help="HTTP port (only used with --transport http)",
)
@click.option(
    "--host",
    type=str,
    default="0.0.0.0",
    help="HTTP host (only used with --transport http)",
)
@click.option(
    "--with-api",
    is_flag=True,
    help="Enable REST API alongside MCP server (dual-mode)",
)
@click.option(
    "--api-prefix",
    type=str,
    default="/api/v1",
    help="REST API URL prefix (default: /api/v1)",
)
@click.option(
    "--api-docs",
    is_flag=True,
    help="Enable OpenAPI docs at /docs (only with --with-api)",
)
@click.pass_context
def serve(
    ctx: click.Context,
    no_watch: bool,
    mode: str | None,
    transport: str,
    port: int,
    host: str,
    with_api: bool,
    api_prefix: str,
    api_docs: bool,
) -> None:
    """Start AEL as MCP server.

    Use --with-api to enable REST API alongside MCP server (dual-mode).
    """
    from ploston_core.config import ConfigLoader, MCPHTTPConfig, Mode, ModeManager, StagedConfig
    from ploston_core.errors import AELError
    from ploston_core.types import MCPTransport

    def print_stderr(msg: str) -> None:
        """Print message to stderr with [AEL] prefix."""
        click.echo(f"[AEL] {msg}", err=True)

    # Convert transport string to enum
    transport_enum = MCPTransport.HTTP if transport == "http" else MCPTransport.STDIO

    async def _serve() -> None:
        config_loader = ConfigLoader()
        config = None
        config_source = None
        initial_mode: Mode

        # Determine initial mode
        if mode == "configuration":
            # Forced configuration mode
            initial_mode = Mode.CONFIGURATION
            print_stderr("Mode: configuration (forced via --mode flag)")
            print_stderr("Use config tools to set up AEL")
        elif mode == "running":
            # Forced running mode - fail fast if no config
            try:
                config = config_loader.load(ctx.obj["config_path"])
                config_source = config_loader._config_path
                initial_mode = Mode.RUNNING
                print_stderr(f"Config loaded from: {config_source}")
                print_stderr("Mode: running (forced via --mode flag)")
            except AELError as e:
                print_stderr(f"Error: {e.message}")
                print_stderr("Cannot start in running mode without valid config")
                sys.exit(1)
        else:
            # Auto-detect mode
            try:
                config = config_loader.load(ctx.obj["config_path"])
                config_source = config_loader._config_path
                initial_mode = Mode.RUNNING
                print_stderr(f"Config loaded from: {config_source}")
                print_stderr("Mode: running")
            except AELError:
                initial_mode = Mode.CONFIGURATION
                print_stderr("No config found (searched: ./ael-config.yaml, ~/.ael/config.yaml)")
                print_stderr("Mode: configuration")
                print_stderr("Use config tools to set up AEL")

        # Create mode manager
        mode_manager = ModeManager(initial_mode=initial_mode)

        # Print transport info
        if transport_enum == MCPTransport.HTTP:
            print_stderr(f"Transport: HTTP on {host}:{port}")
            if with_api:
                print_stderr(f"REST API: enabled at {api_prefix}")
                if api_docs:
                    print_stderr(f"OpenAPI docs: http://{host}:{port}{api_prefix}/docs")
        else:
            print_stderr("Transport: stdio")
            if with_api:
                print_stderr("Warning: --with-api requires --transport http, ignoring")

        if initial_mode == Mode.RUNNING and config:
            # Full initialization for running mode
            app = AELApplication(
                ctx.obj["config_path"],
                log_output=sys.stderr,
                transport=transport_enum,
                http_host=host,
                http_port=port,
                with_rest_api=with_api and transport_enum == MCPTransport.HTTP,
                rest_api_prefix=api_prefix,
                rest_api_docs=api_docs,
            )
            await app.initialize()

            # Print additional info
            if app.mcp_manager:
                servers = list(app.mcp_manager._connections.keys())
                if servers:
                    print_stderr(f"MCP servers: {', '.join(servers)} ({len(servers)})")
            if app.workflow_registry:
                workflows = app.workflow_registry.list_workflows()
                print_stderr(f"Workflows: {len(workflows)} registered")

            if not app.mcp_frontend:
                print_stderr("Error: MCP frontend not initialized")
                sys.exit(1)

            frontend = app.mcp_frontend

            if not no_watch:
                app.start_watching()

            try:
                await frontend.start()
            finally:
                if not no_watch:
                    app.stop_watching()
                await app.shutdown()
        else:
            # Configuration mode - minimal initialization
            from ploston_core.config.tools import ConfigToolRegistry
            from ploston_core.mcp_frontend import MCPFrontend, MCPServerConfig

            # Create staged config
            staged_config = StagedConfig(config_loader)

            # Create config tool registry
            config_tool_registry = ConfigToolRegistry(
                staged_config=staged_config,
                config_loader=config_loader,
            )

            # Create HTTP config if using HTTP transport
            http_config = (
                MCPHTTPConfig(host=host, port=port) if transport_enum == MCPTransport.HTTP else None
            )

            # Create minimal MCP frontend for config mode
            frontend = MCPFrontend(
                workflow_engine=None,
                tool_registry=None,
                workflow_registry=None,
                tool_invoker=None,
                config=MCPServerConfig(),
                logger=None,
                mode_manager=mode_manager,
                config_tool_registry=config_tool_registry,
                transport=transport_enum,
                http_config=http_config,
            )

            try:
                await frontend.start()
            finally:
                pass  # No cleanup needed in config mode

    asyncio.run(_serve())


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
    """Execute a workflow."""

    async def _run() -> None:
        # Parse inputs
        input_dict = parse_inputs(inputs, input_file)

        # Initialize
        app = AELApplication(ctx.obj["config_path"])
        await app.initialize()

        try:
            # Run workflow
            result = await app.run_workflow(workflow, input_dict, timeout)

            # Output result
            if ctx.obj["json_output"]:
                # Convert result to dict for JSON output
                result_dict = {
                    "status": result.status.value,
                    "execution_id": result.execution_id,
                    "outputs": result.outputs,
                    "error": result.error.message if result.error else None,
                }
                click.echo(json.dumps(result_dict, indent=2))
            else:
                # Simple text output
                click.echo(f"Status: {result.status.value}")
                click.echo(f"Execution ID: {result.execution_id}")
                if result.outputs:
                    click.echo("Outputs:")
                    for key, value in result.outputs.items():
                        click.echo(f"  {key}: {value}")
                if result.error:
                    # Handle both AELError (with .message) and regular exceptions
                    error_msg = getattr(result.error, "message", str(result.error))
                    click.echo(f"Error: {error_msg}", err=True)

        finally:
            await app.shutdown()

    asyncio.run(_run())


@cli.command()
def version() -> None:
    """Show version information."""
    click.echo(f"AEL version {__version__}")


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--strict", is_flag=True, help="Treat warnings as errors")
@click.option("--check-tools", is_flag=True, help="Verify tools exist (requires MCP connection)")
@click.pass_context
def validate(ctx: click.Context, file: str, strict: bool, check_tools: bool) -> None:
    """Validate a workflow YAML file."""
    from pathlib import Path

    from ploston_core.workflow import WorkflowValidator, parse_workflow_yaml

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
        workflow = parse_workflow_yaml(yaml_content, file_path)
    except Exception as e:
        errors.append(f"YAML parse error: {e}")
        if ctx.obj["json_output"]:
            click.echo(json.dumps({"valid": False, "errors": errors, "warnings": []}, indent=2))
        else:
            print_validation_result(str(file), errors, warnings)
        sys.exit(1)

    # Validate with or without tool checking
    if check_tools:
        # Need to initialize app to get tool registry
        async def _validate_with_tools() -> tuple[list[str], list[str]]:
            app = AELApplication(ctx.obj["config_path"])
            await app.initialize()

            if not app.workflow_registry:
                await app.shutdown()
                return ["Workflow registry not available"], []

            # Use the validator from workflow registry
            result = app.workflow_registry._validator.validate(workflow, check_tools=True)
            await app.shutdown()

            errs = [f"{e.path}: {e.message}" for e in result.errors]
            warns = [f"{w.path}: {w.message}" for w in result.warnings]
            return errs, warns

        errors, warnings = asyncio.run(_validate_with_tools())
    else:
        # Validate without tool checking - create a mock tool registry
        from unittest.mock import MagicMock

        mock_registry = MagicMock()
        mock_registry.get.return_value = None  # Won't be called since check_tools=False
        validator = WorkflowValidator(mock_registry)
        result = validator.validate(workflow, check_tools=False)

        errors = [f"{e.path}: {e.message}" for e in result.errors]
        warnings = [f"{w.path}: {w.message}" for w in result.warnings]

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
    """Manage workflows."""
    pass


@workflows.command("list")
@click.pass_context
def workflows_list(ctx: click.Context) -> None:
    """List registered workflows."""

    async def _list() -> list[Any]:
        app = AELApplication(ctx.obj["config_path"])
        await app.initialize()
        if not app.workflow_registry:
            return []
        workflows_list_result: list[Any] = app.workflow_registry.list_workflows()
        await app.shutdown()
        return workflows_list_result

    workflows_result = asyncio.run(_list())

    if ctx.obj["json_output"]:
        # Convert to dict for JSON output
        workflows_data = [
            {"name": w.name, "version": w.version, "description": w.description}
            for w in workflows_result
        ]
        click.echo(json.dumps(workflows_data, indent=2))
    else:
        click.echo(f"Total workflows: {len(workflows_result)}")
        for w in workflows_result:
            click.echo(f"  - {w.name} (v{w.version}): {w.description}")


@workflows.command("show")
@click.argument("name")
@click.pass_context
def workflows_show(ctx: click.Context, name: str) -> None:
    """Show workflow details."""
    from .formatters import print_workflow_detail

    async def _show() -> tuple[Any, list[Any] | None]:
        app = AELApplication(ctx.obj["config_path"])
        await app.initialize()

        if not app.workflow_registry:
            await app.shutdown()
            return None, None

        workflow = app.workflow_registry.get(name)
        suggestions = None
        if not workflow:
            # Get all workflows for suggestions
            all_workflows = app.workflow_registry.list_workflows()
            # Simple substring match for suggestions
            suggestions = [w for w in all_workflows if name.lower() in w.name.lower()][:5]

        await app.shutdown()
        return workflow, suggestions

    workflow, suggestions = asyncio.run(_show())

    if not workflow:
        click.echo(f"Error: Workflow '{name}' not found", err=True)
        if suggestions:
            click.echo("\nAvailable workflows:")
            for w in suggestions:
                click.echo(f"  - {w.name}")
        sys.exit(1)

    if ctx.obj["json_output"]:
        workflow_dict = {
            "name": workflow.name,
            "version": workflow.version,
            "description": workflow.description,
            "inputs": [
                {
                    "name": inp.name,
                    "type": inp.type,
                    "required": inp.required,
                    "default": inp.default,
                    "description": inp.description,
                }
                for inp in workflow.inputs
            ],
            "steps": [
                {
                    "id": step.id,
                    "tool": step.tool,
                    "code": "inline" if step.code else None,
                }
                for step in workflow.steps
            ],
            "outputs": [
                {
                    "name": out.name,
                    "from": out.from_path,
                    "description": out.description,
                }
                for out in workflow.outputs
            ],
        }
        click.echo(json.dumps(workflow_dict, indent=2))
    else:
        print_workflow_detail(workflow)


# Valid config sections
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
    """Manage configuration."""
    pass


@config.command("show")
@click.option("--section", help="Show specific section")
@click.pass_context
def config_show(ctx: click.Context, section: str | None) -> None:
    """Show current configuration."""
    from ploston_core.config import ConfigLoader
    from ploston_core.errors import AELError

    from .formatters import dataclass_to_dict, print_config_yaml

    # Validate section if provided
    if section and section not in VALID_SECTIONS:
        click.echo(f"Error: Unknown section '{section}'", err=True)
        click.echo(f"\nValid sections:\n  {', '.join(VALID_SECTIONS)}")
        sys.exit(1)

    # Load config
    loader = ConfigLoader()
    try:
        loaded_config = loader.load(ctx.obj["config_path"])
        source = loader._config_path
    except AELError as e:
        click.echo(f"Error: {e.message}", err=True)
        click.echo("\nSearched:")
        click.echo("  - ./ael-config.yaml")
        click.echo("  - ~/.ael/config.yaml")
        click.echo("\nUse 'ael serve' to start in configuration mode.")
        sys.exit(1)

    # Get data
    if section:
        section_data = getattr(loaded_config, section, None)
        data = dataclass_to_dict(section_data)
    else:
        data = dataclass_to_dict(loaded_config)

    # Output
    if ctx.obj["json_output"]:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        if not section:
            click.echo("AEL Configuration")
            click.echo(f"Source: {source}\n")
        print_config_yaml(data, section)


@cli.group()
def tools() -> None:
    """Manage tools."""
    pass


@tools.command("list")
@click.option("--source", type=click.Choice(["mcp", "system"]), help="Filter by source")
@click.option("--server", help="Filter by MCP server name")
@click.option("--status", type=click.Choice(["available", "unavailable"]), help="Filter by status")
@click.pass_context
def tools_list(
    ctx: click.Context, source: str | None, server: str | None, status: str | None
) -> None:
    """List available tools."""
    from ploston_core.types import ToolSource, ToolStatus

    from .formatters import print_tools_list

    async def _list() -> list[Any]:
        app = AELApplication(ctx.obj["config_path"])
        await app.initialize()

        if not app.tool_registry:
            await app.shutdown()
            return []

        # Convert string options to enums (enum values are lowercase)
        source_enum = ToolSource(source) if source else None
        status_enum = ToolStatus(status) if status else None

        tools_result = app.tool_registry.list_tools(
            source=source_enum,
            server_name=server,
            status=status_enum,
        )

        await app.shutdown()
        return tools_result

    tools_result = asyncio.run(_list())

    if ctx.obj["json_output"]:
        # Convert to dict for JSON output
        tools_data = [
            {
                "name": t.name,
                "description": t.description,
                "source": t.source.value,
                "server_name": t.server_name,
                "status": t.status.value,
            }
            for t in tools_result
        ]
        click.echo(json.dumps(tools_data, indent=2))
    else:
        print_tools_list(tools_result)


@tools.command("show")
@click.argument("name")
@click.pass_context
def tools_show(ctx: click.Context, name: str) -> None:
    """Show tool details."""
    from .formatters import print_tool_detail

    async def _show() -> tuple[Any, list[Any] | None]:
        app = AELApplication(ctx.obj["config_path"])
        await app.initialize()

        if not app.tool_registry:
            await app.shutdown()
            return None, None

        tool = app.tool_registry.get(name)
        suggestions = None
        if not tool:
            # Find similar tools for suggestion
            suggestions = app.tool_registry.search(name)[:5]

        await app.shutdown()
        return tool, suggestions

    tool, suggestions = asyncio.run(_show())

    if not tool:
        click.echo(f"Error: Tool '{name}' not found", err=True)
        if suggestions:
            click.echo("\nDid you mean:")
            for t in suggestions:
                click.echo(f"  - {t.name}")
        sys.exit(1)

    if ctx.obj["json_output"]:
        tool_dict = {
            "name": tool.name,
            "description": tool.description,
            "source": tool.source.value,
            "server_name": tool.server_name,
            "status": tool.status.value,
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
        }
        click.echo(json.dumps(tool_dict, indent=2))
    else:
        print_tool_detail(tool)


@tools.command("refresh")
@click.option("--server", help="Refresh specific server only")
@click.pass_context
def tools_refresh(ctx: click.Context, server: str | None) -> None:
    """Refresh tool schemas from MCP servers."""
    from .formatters import print_refresh_result

    async def _refresh() -> Any:
        app = AELApplication(ctx.obj["config_path"])
        await app.initialize()

        if not app.tool_registry:
            await app.shutdown()
            return None

        if server:
            result = await app.tool_registry.refresh_server(server)
        else:
            result = await app.tool_registry.refresh()

        await app.shutdown()
        return result

    click.echo("Refreshing tools...")
    result = asyncio.run(_refresh())

    if result is None:
        click.echo("Error: Tool registry not available", err=True)
        sys.exit(1)

    if ctx.obj["json_output"]:
        result_dict = {
            "total_tools": result.total_tools,
            "added": result.added,
            "removed": result.removed,
            "updated": result.updated,
            "errors": result.errors,
        }
        click.echo(json.dumps(result_dict, indent=2))
    else:
        print_refresh_result(result)


@cli.command()
@click.option("--host", type=str, default="0.0.0.0", help="Host to bind to")
@click.option("--port", type=int, default=8080, help="Port to bind to")
@click.option("--prefix", type=str, default="/api/v1", help="API prefix")
@click.option("--no-docs", is_flag=True, help="Disable OpenAPI docs")
@click.option("--require-auth", is_flag=True, help="Require API key authentication")
@click.option("--rate-limit", type=int, default=0, help="Requests per minute (0=disabled)")
@click.option("--db", type=click.Path(), help="SQLite database path for execution store")
@click.pass_context
def api(
    ctx: click.Context,
    host: str,
    port: int,
    prefix: str,
    no_docs: bool,
    require_auth: bool,
    rate_limit: int,
    db: str | None,
) -> None:
    """Start AEL REST API server."""
    import uvicorn
    from ploston_core.api import RESTConfig, create_rest_app

    def print_stderr(msg: str) -> None:
        """Print message to stderr with [AEL] prefix."""
        click.echo(f"[AEL] {msg}", err=True)

    async def _api() -> None:
        # Initialize AEL application
        app = AELApplication(ctx.obj["config_path"], log_output=sys.stderr)
        await app.initialize()

        if not app.workflow_registry or not app.workflow_engine:
            print_stderr("Error: Workflow components not initialized")
            sys.exit(1)

        if not app.tool_registry or not app.tool_invoker:
            print_stderr("Error: Tool components not initialized")
            sys.exit(1)

        # Create REST config
        rest_config = RESTConfig(
            host=host,
            port=port,
            prefix=prefix,
            docs_enabled=not no_docs,
            require_auth=require_auth,
            rate_limiting_enabled=rate_limit > 0,
            requests_per_minute=rate_limit if rate_limit > 0 else 100,
            execution_store_sqlite_path=db,
        )

        # Create FastAPI app
        fastapi_app = create_rest_app(
            workflow_registry=app.workflow_registry,
            workflow_engine=app.workflow_engine,
            tool_registry=app.tool_registry,
            tool_invoker=app.tool_invoker,
            config=rest_config,
            logger=app.logger,
        )

        print_stderr(f"REST API starting on http://{host}:{port}")
        print_stderr(f"API prefix: {prefix}")
        if not no_docs:
            print_stderr(f"OpenAPI docs: http://{host}:{port}/docs")

        # Run uvicorn
        config = uvicorn.Config(
            fastapi_app,
            host=host,
            port=port,
            log_level="info",
        )
        server = uvicorn.Server(config)

        try:
            await server.serve()
        finally:
            await app.shutdown()

    asyncio.run(_api())


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
