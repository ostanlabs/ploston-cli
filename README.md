# Ploston CLI

Command-line interface for Ploston - Deterministic Agent Execution Layer

## Overview

The Ploston CLI provides a powerful command-line interface for interacting with Ploston servers.
It works with both the open-source community tier and enterprise tier.

## Installation

### From PyPI

```bash
pip install ploston-cli
```

### From Source

```bash
git clone https://github.com/ostanlabs/ploston-cli.git
cd ploston-cli
make install
```

### Verify Installation

```bash
ploston version
```

## Quick Start

```bash
# Start the MCP server
ploston serve

# List available workflows
ploston workflows list

# Run a workflow
ploston run my-workflow -i key=value

# Validate a workflow file
ploston validate workflow.yaml
```

## Commands

### Global Options

| Option | Description |
|--------|-------------|
| `-c, --config PATH` | Config file path |
| `-v, --verbose` | Increase verbosity (can be repeated) |
| `-q, --quiet` | Suppress output |
| `--json` | Output as JSON |

### `ploston serve`

Start the MCP server.

```bash
# Start with default settings (stdio transport)
ploston serve

# Start with HTTP transport
ploston serve --transport http --port 8080

# Start with REST API enabled
ploston serve --transport http --with-api --api-docs

# Force configuration mode
ploston serve --mode configuration
```

| Option | Default | Description |
|--------|---------|-------------|
| `--transport` | `stdio` | Transport type (`stdio` or `http`) |
| `--host` | `0.0.0.0` | HTTP host |
| `--port` | `8080` | HTTP port |
| `--no-watch` | `false` | Disable config hot-reload |
| `--mode` | auto | Force mode (`configuration` or `running`) |
| `--with-api` | `false` | Enable REST API (HTTP only) |
| `--api-prefix` | `/api/v1` | REST API URL prefix |
| `--api-docs` | `false` | Enable OpenAPI docs at /docs |

### `ploston run`

Execute a workflow.

```bash
# Run with inline inputs
ploston run my-workflow -i name=John -i age=30

# Run with input file
ploston run my-workflow --input-file inputs.yaml

# Run with timeout
ploston run my-workflow -t 60

# Get JSON output
ploston --json run my-workflow
```

| Option | Description |
|--------|-------------|
| `-i, --input KEY=VALUE` | Input parameter (can be repeated) |
| `--input-file PATH` | YAML/JSON file with inputs |
| `-t, --timeout SECONDS` | Execution timeout |

### `ploston validate`

Validate a workflow YAML file.

```bash
# Basic validation
ploston validate workflow.yaml

# Strict mode (warnings as errors)
ploston validate --strict workflow.yaml

# Check that tools exist (requires MCP connection)
ploston validate --check-tools workflow.yaml
```

| Option | Description |
|--------|-------------|
| `--strict` | Treat warnings as errors |
| `--check-tools` | Verify tools exist |

### `ploston workflows`

Manage workflows.

```bash
# List all workflows
ploston workflows list

# Show workflow details
ploston workflows show my-workflow

# JSON output
ploston --json workflows list
```

### `ploston tools`

Manage tools.

```bash
# List all tools
ploston tools list

# Filter by source
ploston tools list --source mcp

# Filter by server
ploston tools list --server native-tools

# Show tool details
ploston tools show read_file

# Refresh tool schemas
ploston tools refresh
ploston tools refresh --server native-tools
```

| Option | Description |
|--------|-------------|
| `--source` | Filter by source (`mcp` or `system`) |
| `--server` | Filter by MCP server name |
| `--status` | Filter by status (`available` or `unavailable`) |

### `ploston config`

Manage configuration.

```bash
# Show full config
ploston config show

# Show specific section
ploston config show --section mcp

# JSON output
ploston --json config show
```

Valid sections: `server`, `mcp`, `tools`, `workflows`, `execution`, `python_exec`, `logging`, `plugins`, `security`, `telemetry`

### `ploston api`

Start standalone REST API server.

```bash
# Start API server
ploston api --port 8080

# With authentication required
ploston api --require-auth

# With rate limiting
ploston api --rate-limit 100

# With SQLite execution store
ploston api --db ./executions.db
```

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `0.0.0.0` | Host to bind to |
| `--port` | `8080` | Port to bind to |
| `--prefix` | `/api/v1` | API prefix |
| `--no-docs` | `false` | Disable OpenAPI docs |
| `--require-auth` | `false` | Require API key |
| `--rate-limit` | `0` | Requests per minute (0=disabled) |
| `--db` | - | SQLite database path |

### `ploston version`

Show version information.

```bash
ploston version
```

## Configuration

The CLI looks for configuration in the following order:

1. Path specified with `-c/--config`
2. `./ael-config.yaml` (current directory)
3. `~/.ael/config.yaml` (home directory)

If no config is found, the server starts in **configuration mode** where you can use MCP tools to set up the configuration.

### Example Config

```yaml
# ael-config.yaml
server:
  host: 0.0.0.0
  port: 8080

mcp:
  servers:
    native-tools:
      command: python
      args: ["-m", "native_tools"]

workflows:
  paths:
    - ./workflows/

logging:
  level: INFO
```

## JSON Output

All commands support `--json` for machine-readable output:

```bash
# List workflows as JSON
ploston --json workflows list

# Run workflow with JSON output
ploston --json run my-workflow -i key=value

# Validate with JSON output
ploston --json validate workflow.yaml
```

## Development

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager

### Setup

```bash
make install
```

### Commands

```bash
make help       # Show all commands
make test       # Run all tests
make test-unit  # Run unit tests only
make lint       # Run linter
make format     # Format code
make check      # Run lint + tests
make build      # Build package
```

## Features

- **HTTP-only client**: No server dependencies, works with any Ploston server
- **Tier detection**: Automatically detects community vs enterprise features
- **Rich output**: Beautiful terminal output with colors and formatting
- **JSON mode**: Machine-readable output for scripting
- **Config hot-reload**: Automatically reloads config changes
- **Dual-mode server**: Run MCP and REST API simultaneously

## License

Apache-2.0
