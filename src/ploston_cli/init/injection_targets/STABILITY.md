# Injection Targets — API Stability (DEC-204, DEC-206)

## Public API (stable)

These symbols are importable, documented, and follow semver:

| Symbol | Module | Description |
|--------|--------|-------------|
| `ConfigAdapter` | `base.py` | Protocol — 8 methods (read, write, get_servers, set_servers, get_backup_section, set_backup_section, strip_backup_section, decorate_server_entry) |
| `InjectionTarget` | `base.py` | Base class for all targets |
| `TARGET_REGISTRY` | `registry.py` | `dict[str, InjectionTarget]` dispatch table |
| `McpServersAdapter` | `adapters.py` | Adapter for `{"mcpServers": {...}}` JSON |
| `MicrosoftServersAdapter` | `adapters.py` | Adapter for `{"servers": {...}}` Microsoft JSON |

**Adding a new target?** Subclass `InjectionTarget`, pick an adapter (`McpServersAdapter`, `MicrosoftServersAdapter`, or compose your own via `CompositeAdapter`), and register in `registry.py`.

## Internal API (unstable)

These symbols power the public adapters but may change without semver notice:

| Symbol | Module | Notes |
|--------|--------|-------|
| `ConfigFormat` | `formats.py` | Protocol for file I/O (read/write) |
| `ConfigShape` | `shapes.py` | Protocol for data structure operations |
| `CompositeAdapter` | `composite.py` | Composes a Format + Shape into a ConfigAdapter |
| `JsonFormat` | `formats.py` | JSON file format |
| `TomlFormat` | `formats.py` | TOML file format via tomlkit |
| `McpServersShape` | `shapes.py` | Shape for `mcpServers` / `mcp_servers` keys |
| `MicrosoftServersShape` | `shapes.py` | Shape for Microsoft `servers` key |
| `ContextServersShape` | `shapes.py` | Shape for Zed `context_servers` key |

**Why internal?** Wave 3 (Continue.dev, potential YAML support) may revise these protocols. Third-party code can use them today, but with the caveat that signatures may change.

## Adding a new format

1. Implement the `ConfigFormat` protocol (2 methods: `read`, `write`).
2. Compose with an existing shape: `CompositeAdapter(YourFormat(), McpServersShape())`.
3. Register the target in `registry.py`.

## Adding a new shape

1. Implement the `ConfigShape` protocol (6 methods).
2. Compose with an existing format: `CompositeAdapter(JsonFormat(), YourShape())`.
3. Register the target in `registry.py`.
