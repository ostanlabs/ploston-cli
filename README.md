# ploston-cli

CLI for Ploston - Deterministic Agent Execution Layer

## Overview

This package provides the command-line interface for interacting with Ploston servers.
It works with both the open-source community tier and enterprise tier.

## Installation

```bash
pip install ploston-cli
```

## Usage

```bash
# Connect to a server
ploston --server http://localhost:8080 workflows list

# Run a workflow
ploston run my-workflow --input '{"key": "value"}'

# Validate a workflow
ploston validate workflow.yaml
```

## Features

- HTTP-only client (no server dependencies)
- Tier detection via capabilities endpoint
- Enterprise feature prompts
- Rich terminal output

## License

Apache-2.0
