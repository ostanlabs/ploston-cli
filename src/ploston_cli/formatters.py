"""CLI output formatting helpers.

All formatters work with dict responses from the HTTP API.
"""

from typing import Any

import click
import yaml


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


def print_workflow_detail_dict(workflow: dict[str, Any]) -> None:
    """Print workflow details from dict response.

    Args:
        workflow: Workflow dict from API
    """
    click.echo(f"Workflow: {workflow.get('name', 'unknown')}")
    click.echo(f"Version: {workflow.get('version', '?')}")
    if workflow.get("description"):
        click.echo(f"Description: {workflow['description']}")
    click.echo()

    inputs = workflow.get("inputs", [])
    if inputs:
        click.echo("Inputs:")
        for inp in inputs:
            req = (
                "required"
                if inp.get("required", False)
                else f"default: {inp.get('default', 'none')}"
            )
            desc = f": {inp.get('description', '')}" if inp.get("description") else ""
            click.echo(f"  - {inp.get('name', '?')} ({inp.get('type', 'any')}, {req}){desc}")
        click.echo()

    steps = workflow.get("steps", [])
    if steps:
        click.echo("Steps:")
        for i, step in enumerate(steps, 1):
            tool = step.get("tool")
            step_type = f"tool: {tool}" if tool else "code: inline"
            click.echo(f"  {i}. {step.get('id', '?')} ({step_type})")

    outputs = workflow.get("outputs", [])
    if outputs:
        click.echo("\nOutputs:")
        for out in outputs:
            source = out.get("from") or out.get("value") or "unknown"
            click.echo(f"  - {out.get('name', '?')}: from {source}")


def print_tools_list_dict(tools: list[dict[str, Any]]) -> None:
    """Print tools list grouped by source from dict response.

    Args:
        tools: List of tool dicts from API
    """
    # Group by server
    by_server: dict[str, list[dict[str, Any]]] = {}
    system_tools: list[dict[str, Any]] = []

    for tool in tools:
        source = tool.get("source", "")
        if source == "system":
            system_tools.append(tool)
        else:
            server = tool.get("server_name") or "unknown"
            if server not in by_server:
                by_server[server] = []
            by_server[server].append(tool)

    available = sum(1 for t in tools if t.get("status") == "available")
    click.echo(f"Tools ({len(tools)} total, {available} available):\n")

    for server, server_tools in by_server.items():
        click.echo(f"MCP Server: {server} ({len(server_tools)} tools)")
        for tool in server_tools:
            desc = tool.get("description", "")
            if len(desc) > 50:
                desc = desc[:50] + "..."
            click.echo(f"  - {tool.get('name', '?')}: {desc}")
        click.echo()

    if system_tools:
        click.echo(f"System Tools ({len(system_tools)} tools)")
        for tool in system_tools:
            click.echo(f"  - {tool.get('name', '?')}: {tool.get('description', '')}")


def print_tool_detail_dict(tool: dict[str, Any]) -> None:
    """Print tool details from dict response.

    Args:
        tool: Tool dict from API
    """
    click.echo(f"Tool: {tool.get('name', 'unknown')}")
    source = tool.get("source", "unknown")
    click.echo(f"Source: {source}", nl=False)
    if tool.get("server_name"):
        click.echo(f" ({tool['server_name']})")
    else:
        click.echo()
    status = tool.get("status", "unknown")
    click.echo(f"Status: {status.title()}\n")

    click.echo("Description:")
    click.echo(f"  {tool.get('description', 'No description')}\n")

    input_schema = tool.get("input_schema")
    if input_schema:
        click.echo("Input Schema:")
        props = input_schema.get("properties", {})
        required = input_schema.get("required", [])
        for name, schema in props.items():
            req = "required" if name in required else f"default: {schema.get('default', 'none')}"
            desc = schema.get("description", "")
            click.echo(f"  {name} ({schema.get('type', 'any')}, {req}): {desc}")


def print_refresh_result_dict(result: dict[str, Any]) -> None:
    """Print refresh result from dict response.

    Args:
        result: Refresh result dict from API
    """
    click.echo("Refresh complete:")
    click.echo(f"  Total tools: {result.get('total_tools', 0)}")
    added = result.get("added", [])
    updated = result.get("updated", [])
    removed = result.get("removed", [])
    click.echo(f"  Added: {len(added) if isinstance(added, list) else added}")
    click.echo(f"  Updated: {len(updated) if isinstance(updated, list) else updated}")
    click.echo(f"  Removed: {len(removed) if isinstance(removed, list) else removed}")

    errors = result.get("errors", {})
    if errors:
        click.echo("\n  Errors:")
        for server, error in errors.items():
            click.echo(f"    - {server}: {error}")
