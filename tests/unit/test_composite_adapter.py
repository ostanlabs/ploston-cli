"""Tests for CompositeAdapter (S-315, T-1015, T-1016).

Verifies:
- CompositeAdapter satisfies the ConfigAdapter Protocol
- McpServersAdapter post-refactor behaves identically
- MicrosoftServersAdapter post-refactor behaves identically
"""

from __future__ import annotations

import json
from pathlib import Path

from ploston_cli.init.injection_targets.adapters import McpServersAdapter, MicrosoftServersAdapter
from ploston_cli.init.injection_targets.base import ConfigAdapter
from ploston_cli.init.injection_targets.composite import CompositeAdapter
from ploston_cli.init.injection_targets.formats import JsonFormat, TomlFormat
from ploston_cli.init.injection_targets.shapes import McpServersShape


class TestCompositeAdapterProtocol:
    """S-315 gate: CompositeAdapter satisfies ConfigAdapter Protocol."""

    def test_composite_adapter_satisfies_config_adapter(self):
        adapter = CompositeAdapter(format=JsonFormat(), shape=McpServersShape())
        assert isinstance(adapter, ConfigAdapter)

    def test_mcp_servers_adapter_is_composite(self):
        adapter = McpServersAdapter()
        assert isinstance(adapter, CompositeAdapter)
        assert isinstance(adapter, ConfigAdapter)

    def test_microsoft_servers_adapter_is_composite(self):
        adapter = MicrosoftServersAdapter()
        assert isinstance(adapter, CompositeAdapter)
        assert isinstance(adapter, ConfigAdapter)

    def test_toml_composite_satisfies_protocol(self):
        adapter = CompositeAdapter(
            format=TomlFormat(), shape=McpServersShape(servers_key="mcp_servers")
        )
        assert isinstance(adapter, ConfigAdapter)


class TestMcpServersAdapterPostRefactor:
    """S-315: McpServersAdapter behaves identically after CompositeAdapter refactor."""

    def test_round_trip(self, tmp_path: Path):
        p = tmp_path / "config.json"
        seed = {"mcpServers": {"test": {"command": "echo"}}, "otherKey": 42}
        p.write_text(json.dumps(seed), encoding="utf-8")

        adapter = McpServersAdapter()
        data = adapter.read(p)
        assert adapter.get_servers(data) == {"test": {"command": "echo"}}

        # Set servers
        new_data = adapter.set_servers(
            data, {"test": {"command": "echo"}, "ploston": {"command": "ploston"}}
        )
        adapter.write(p, new_data)

        # Re-read
        data2 = adapter.read(p)
        assert "ploston" in adapter.get_servers(data2)
        assert data2["otherKey"] == 42  # Sibling preserved

    def test_backup_operations(self, tmp_path: Path):
        adapter = McpServersAdapter()
        data = {"mcpServers": {"test": {"command": "echo"}}}

        backup = {"test": {"command": "echo"}}
        data = adapter.set_backup_section(data, backup)
        assert adapter.get_backup_section(data) == backup

        stripped = adapter.strip_backup_section(data)
        assert "_ploston_imported" not in stripped

    def test_decorate_is_noop(self):
        adapter = McpServersAdapter()
        entry = {"command": "ploston", "args": ["bridge"]}
        assert adapter.decorate_server_entry(entry) == entry


class TestMicrosoftServersAdapterPostRefactor:
    """S-315: MicrosoftServersAdapter behaves identically after refactor."""

    def test_round_trip_with_inputs(self, tmp_path: Path):
        p = tmp_path / "mcp.json"
        seed = {
            "servers": {"test": {"command": "echo", "type": "stdio"}},
            "inputs": [{"type": "promptString", "id": "token"}],
        }
        p.write_text(json.dumps(seed), encoding="utf-8")

        adapter = MicrosoftServersAdapter()
        data = adapter.read(p)
        assert adapter.get_servers(data) == {"test": {"command": "echo", "type": "stdio"}}

        adapter.write(p, data)
        data2 = adapter.read(p)
        assert data2.get("inputs") == [{"type": "promptString", "id": "token"}]

    def test_decorate_adds_type_stdio(self):
        adapter = MicrosoftServersAdapter()
        entry = {"command": "ploston", "args": ["bridge"]}
        decorated = adapter.decorate_server_entry(entry)
        assert decorated["type"] == "stdio"
        # Original not mutated
        assert "type" not in entry
