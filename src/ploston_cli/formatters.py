"""CLI output formatting helpers."""

import dataclasses
from typing import Any

import click
import yaml


def dataclass_to_dict(obj: Any) -> dict[str, Any]:
    """Convert dataclass to dict, handling nested dataclasses.

    Args:
        obj: Dataclass instance or dict

    Returns:
        Dictionary representation
    """
    if obj is None:
        return {}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, dict):
        return obj
    return {}


def print_config_yaml(data: dict[str, Any], section: str | None = None) -> None:
    """Print config as YAML.

    Args:
        data: Configuration data
        section: Optional section name for header
    """
    if section:
        click.echo(f"{section}:")
        # Indent the output
        yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)
        for line in yaml_str.splitlines():
            click.echo(f"  {line}")
    else:
        click.echo(yaml.dump(data, default_flow_style=False, sort_keys=False))


def print_validation_result(file: str, errors: list[str], warnings: list[str]) -> None:
    """Print validation results.

    Args:
        file: File being validated
        errors: List of error messages
        warnings: List of warning messages
    """
    click.echo(f"Validating: {file}\n")

    if errors:
        click.echo("ERRORS:")
        for e in errors:
            click.echo(f"  ✗ {e}")

    if warnings:
        click.echo("WARNINGS:")
        for w in warnings:
            click.echo(f"  ⚠ {w}")

    if not errors and not warnings:
        click.echo("✓ Validation passed")
    elif errors:
        click.echo(f"\nValidation failed with {len(errors)} errors and {len(warnings)} warnings")


def print_workflow_detail(workflow: Any) -> None:
    """Print workflow details.

    Args:
        workflow: Workflow definition object
    """
    click.echo(f"Workflow: {workflow.name}")
    click.echo(f"Version: {workflow.version}")
    if workflow.description:
        click.echo(f"Description: {workflow.description}")
    click.echo()

    if workflow.inputs:
        click.echo("Inputs:")
        for inp in workflow.inputs:
            req = "required" if inp.required else f"default: {inp.default}"
            desc = f": {inp.description}" if inp.description else ""
            click.echo(f"  - {inp.name} ({inp.type}, {req}){desc}")
        click.echo()

    click.echo("Steps:")
    for i, step in enumerate(workflow.steps, 1):
        step_type = f"tool: {step.tool}" if step.tool else "code: inline"
        click.echo(f"  {i}. {step.id} ({step_type})")

    if workflow.outputs:
        click.echo("\nOutputs:")
        for out in workflow.outputs:
            source = out.from_path or out.value or "unknown"
            click.echo(f"  - {out.name}: from {source}")


def print_tools_list(tools: list[Any]) -> None:
    """Print tools list grouped by source.

    Args:
        tools: List of tool entries
    """
    from ploston_core.types import ToolSource, ToolStatus

    # Group by server
    by_server: dict[str, list[Any]] = {}
    system_tools: list[Any] = []

    for tool in tools:
        if tool.source == ToolSource.SYSTEM:
            system_tools.append(tool)
        else:
            server = tool.server_name or "unknown"
            if server not in by_server:
                by_server[server] = []
            by_server[server].append(tool)

    available = sum(1 for t in tools if t.status == ToolStatus.AVAILABLE)
    click.echo(f"Tools ({len(tools)} total, {available} available):\n")

    for server, server_tools in by_server.items():
        click.echo(f"MCP Server: {server} ({len(server_tools)} tools)")
        for tool in server_tools:
            desc = tool.description[:50] + "..." if len(tool.description) > 50 else tool.description
            click.echo(f"  - {tool.name}: {desc}")
        click.echo()

    if system_tools:
        click.echo(f"System Tools ({len(system_tools)} tools)")
        for tool in system_tools:
            click.echo(f"  - {tool.name}: {tool.description}")


def print_tool_detail(tool: Any) -> None:
    """Print tool details.

    Args:
        tool: Tool entry object
    """
    click.echo(f"Tool: {tool.name}")
    click.echo(f"Source: {tool.source.value}", nl=False)
    if tool.server_name:
        click.echo(f" ({tool.server_name})")
    else:
        click.echo()
    click.echo(f"Status: {tool.status.value.title()}\n")

    click.echo("Description:")
    click.echo(f"  {tool.description}\n")

    if tool.input_schema:
        click.echo("Input Schema:")
        props = tool.input_schema.get("properties", {})
        required = tool.input_schema.get("required", [])
        for name, schema in props.items():
            req = "required" if name in required else f"default: {schema.get('default', 'none')}"
            desc = schema.get("description", "")
            click.echo(f"  {name} ({schema.get('type', 'any')}, {req}): {desc}")


def print_refresh_result(result: Any) -> None:
    """Print refresh result.

    Args:
        result: Refresh result object
    """
    click.echo("Refresh complete:")
    click.echo(f"  Total tools: {result.total_tools}")
    click.echo(f"  Added: {len(result.added)}")
    click.echo(f"  Updated: {len(result.updated)}")
    click.echo(f"  Removed: {len(result.removed)}")

    if result.errors:
        click.echo("\n  Errors:")
        for server, error in result.errors.items():
            click.echo(f"    - {server}: {error}")
