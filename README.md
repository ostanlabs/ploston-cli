# Ploston CLI

Command-line interface for Ploston - Deterministic Agent Execution Layer

## Overview

The Ploston CLI is a **thin HTTP client** for interacting with Ploston servers.
It works with both the open-source community tier and enterprise tier.

**Key Design Principle**: The CLI does not embed any server components. It communicates
exclusively via HTTP with a running Ploston server.

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
# Configure server URL (one-time setup)
ploston config set server http://localhost:8080

# Or use environment variable
export PLOSTON_SERVER=http://localhost:8080

# List available workflows
ploston workflows list

# Run a workflow
ploston run my-workflow -i key=value

# Validate a workflow file (local validation)
ploston validate workflow.yaml
```

## Server Connection

The CLI connects to a Ploston server via HTTP. Configure the server URL using:

1. **CLI flag**: `--server http://localhost:8080`
2. **Environment variable**: `PLOSTON_SERVER=http://localhost:8080`
3. **Config file**: `~/.ploston/config.yaml`

```bash
# Set server URL in config
ploston config set server http://localhost:8080

# Check current configuration
ploston config show --local
```

## Commands

### Global Options

| Option | Description |
|--------|-------------|
| `--server URL` | Ploston server URL |
| `-v, --verbose` | Increase verbosity (can be repeated) |
| `-q, --quiet` | Suppress output |
| `--json` | Output as JSON |

### `ploston run`

Execute a workflow on the server.

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

Validate a workflow YAML file locally.

```bash
# Basic validation (local only, no server needed)
ploston validate workflow.yaml

# Strict mode (warnings as errors)
ploston validate --strict workflow.yaml

# Check that tools exist on server
ploston validate --check-tools workflow.yaml
```

| Option | Description |
|--------|-------------|
| `--strict` | Treat warnings as errors |
| `--check-tools` | Verify tools exist on server |

### `ploston workflows`

Manage workflows on the server.

```bash
# List all workflows
ploston workflows list

# Show workflow details
ploston workflows show my-workflow

# JSON output
ploston --json workflows list
```

### `ploston tools`

Manage tools on the server.

```bash
# List all tools
ploston tools list

# Show tool details
ploston tools show read_file

# Refresh tool schemas from MCP servers
ploston tools refresh
```

### `ploston config`

Manage CLI and server configuration.

```bash
# Show local CLI config
ploston config show --local

# Show server config
ploston config show

# Show specific section
ploston config show --section mcp

# Set CLI config values
ploston config set server http://localhost:8080
ploston config set timeout 60

# Unset CLI config values
ploston config unset timeout
```

Valid sections: `server`, `mcp`, `tools`, `workflows`, `execution`, `python_exec`, `logging`, `plugins`, `security`, `telemetry`

### `ploston version`

Show version information.

```bash
ploston version
```

Shows both CLI version and connected server version.

### `ploston bridge`

Start MCP bridge for Claude Desktop, Cursor, and other MCP clients.

```bash
# Basic usage
ploston bridge --url http://localhost:8080

# With authentication
ploston bridge --url https://cp.example.com --token plt_xxx

# With custom timeout and logging
ploston bridge --url http://localhost:8080 --timeout 60 --log-level debug
```

| Option | Environment Variable | Description |
|--------|---------------------|-------------|
| `--url` | `PLOSTON_URL` | Control Plane URL (required) |
| `--token` | `PLOSTON_TOKEN` | Bearer token for authentication |
| `--timeout` | `PLOSTON_TIMEOUT` | Request timeout in seconds (default: 30) |
| `--log-level` | `PLOSTON_LOG_LEVEL` | Log level: debug, info, warning, error |
| `--log-file` | `PLOSTON_LOG_FILE` | Log file path (default: ~/.ploston/bridge.log) |
| `--retry-attempts` | `PLOSTON_RETRY_ATTEMPTS` | Startup retry attempts (default: 3) |
| `--retry-delay` | `PLOSTON_RETRY_DELAY` | Delay between retries (default: 1.0s) |

#### Claude Desktop Configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "ploston": {
      "command": "ploston",
      "args": ["bridge", "--url", "http://localhost:8080"],
      "env": {
        "PLOSTON_TOKEN": "your-token-here"
      }
    }
  }
}
```

#### Cursor Configuration

Add to `.cursor/mcp.json` in your project:

```json
{
  "mcpServers": {
    "ploston": {
      "command": "ploston",
      "args": ["bridge", "--url", "http://localhost:8080"],
      "env": {
        "PLOSTON_TOKEN": "your-token-here"
      }
    }
  }
}
```

#### Troubleshooting

**Bridge won't start:**
- Check that the CP URL is correct and reachable
- Verify the token is valid (if authentication is required)
- Check `~/.ploston/bridge.log` for detailed error messages

**Connection drops:**
- The bridge auto-reconnects on connection loss
- Check network connectivity to the CP
- Increase `--timeout` for slow networks

**Tools not appearing:**
- Ensure the CP has tools configured
- Check that your token has permission to access tools
- Run `ploston tools list` to verify tools are available

## Configuration

### CLI Configuration

The CLI stores its configuration in `~/.ploston/config.yaml`:

```yaml
# ~/.ploston/config.yaml
server: http://localhost:8080
timeout: 30
output_format: text
```

Configuration precedence (highest to lowest):
1. CLI flags (`--server`)
2. Environment variables (`PLOSTON_SERVER`)
3. Config file (`~/.ploston/config.yaml`)
4. Default values

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PLOSTON_SERVER` | Server URL | `http://localhost:8080` |
| `PLOSTON_TIMEOUT` | Request timeout (seconds) | `30` |
| `PLOSTON_OUTPUT_FORMAT` | Output format (`text` or `json`) | `text` |

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

## Starting a Server

The CLI is a client only. To start a Ploston server, use the `ploston` package:

```bash
# Install the server package
pip install ploston

# Start the server
ploston-server --port 8080
```

Or use Docker:

```bash
docker run -p 8080:8080 ostanlabs/ploston:latest
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

### Testing

Tests are organized across two locations:

| Test Type | Location | Run Command |
|-----------|----------|-------------|
| Unit tests | `packages/ploston-cli/tests/unit/` | `make test-unit` (in package) |
| Integration tests | `packages/ploston-cli/tests/integration/` | `make test` (in package) |
| E2E tests | `tests/e2e/docker_compose/` (meta-repo) | `make test-e2e-docker-compose` (in meta-repo) |

E2E tests live in the meta-repo because they require:
- Docker Compose infrastructure (CP running)
- Installed CLI (from test-pypi or local build)
- Coordination between multiple components (CLI, CP, Runner)

To run E2E tests:

```bash
# From meta-repo root
make test-e2e-docker-compose
```

## Features

- **HTTP-only client**: No server dependencies, works with any Ploston server
- **Tier detection**: Automatically detects community vs enterprise features from server
- **Rich output**: Beautiful terminal output with colors and formatting
- **JSON mode**: Machine-readable output for scripting
- **Local validation**: Validate workflow YAML without server connection

## License

Apache-2.0
