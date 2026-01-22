"""CLI utility functions."""

import json
from pathlib import Path
from typing import Any

import yaml


def parse_inputs(
    input_flags: tuple[str, ...],
    input_file: str | None,
) -> dict[str, Any]:
    """Parse workflow inputs from flags and file.

    Args:
        input_flags: Tuple of KEY=VALUE strings
        input_file: Path to JSON/YAML file with inputs

    Returns:
        Dictionary of inputs
    """
    inputs: dict[str, Any] = {}

    # Parse input file first (if provided)
    if input_file:
        file_path = Path(input_file)
        with file_path.open() as f:
            if file_path.suffix in [".yaml", ".yml"]:
                inputs = yaml.safe_load(f) or {}
            elif file_path.suffix == ".json":
                inputs = json.load(f)
            else:
                raise ValueError(f"Unsupported input file format: {file_path.suffix}")

    # Parse input flags (override file inputs)
    for input_str in input_flags:
        if "=" not in input_str:
            raise ValueError(f"Invalid input format: {input_str}. Expected KEY=VALUE")

        key, value = input_str.split("=", 1)

        # Try to parse value as JSON (for complex types)
        try:
            inputs[key] = json.loads(value)
        except json.JSONDecodeError:
            # Keep as string if not valid JSON
            inputs[key] = value

    return inputs
