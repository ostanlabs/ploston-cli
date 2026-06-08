"""Specification-driven tests for ploston_cli.utils.parse_inputs.

Contract (from docstring):
  - Inputs come from a file (JSON or YAML) and/or repeated KEY=VALUE flags.
  - Flags OVERRIDE file values.
  - Flag values are parsed as JSON when possible, else kept as strings.
  - Unsupported file extensions and malformed flags raise ValueError.
"""

from __future__ import annotations

import json

import pytest

from ploston_cli.utils import parse_inputs


class TestFlagsOnly:
    def test_empty_returns_empty_dict(self):
        assert parse_inputs((), None) == {}

    def test_string_value_kept_as_string(self):
        assert parse_inputs(("name=alice",), None) == {"name": "alice"}

    def test_value_with_equals_only_split_once(self):
        """Only the first '=' delimits key/value."""
        assert parse_inputs(("expr=a=b=c",), None) == {"expr": "a=b=c"}

    def test_numeric_value_parsed_as_json_int(self):
        assert parse_inputs(("count=5",), None) == {"count": 5}
        assert isinstance(parse_inputs(("count=5",), None)["count"], int)

    def test_bool_and_null_parsed_as_json(self):
        result = parse_inputs(("flag=true", "missing=null"), None)
        assert result["flag"] is True
        assert result["missing"] is None

    def test_json_array_and_object_parsed(self):
        result = parse_inputs(("items=[1,2,3]", 'cfg={"a":1}'), None)
        assert result["items"] == [1, 2, 3]
        assert result["cfg"] == {"a": 1}

    def test_non_json_string_kept_raw(self):
        # A value that fails JSON parse stays a string
        assert parse_inputs(("path=/var/log",), None) == {"path": "/var/log"}

    def test_later_flag_overrides_earlier(self):
        assert parse_inputs(("x=1", "x=2"), None) == {"x": 2}

    def test_missing_equals_raises_valueerror(self):
        with pytest.raises(ValueError, match="Expected KEY=VALUE"):
            parse_inputs(("noequals",), None)


class TestFileInputs:
    def test_json_file_loaded(self, tmp_path):
        f = tmp_path / "inputs.json"
        f.write_text(json.dumps({"a": 1, "b": "two"}))
        assert parse_inputs((), str(f)) == {"a": 1, "b": "two"}

    def test_yaml_file_loaded(self, tmp_path):
        f = tmp_path / "inputs.yaml"
        f.write_text("a: 1\nb: two\n")
        assert parse_inputs((), str(f)) == {"a": 1, "b": "two"}

    def test_yml_extension_loaded(self, tmp_path):
        f = tmp_path / "inputs.yml"
        f.write_text("k: v\n")
        assert parse_inputs((), str(f)) == {"k": "v"}

    def test_empty_yaml_file_yields_empty_dict(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("")
        assert parse_inputs((), str(f)) == {}

    def test_unsupported_extension_raises(self, tmp_path):
        f = tmp_path / "inputs.txt"
        f.write_text("a=1")
        with pytest.raises(ValueError, match="Unsupported input file format"):
            parse_inputs((), str(f))

    def test_flags_override_file_values(self, tmp_path):
        f = tmp_path / "inputs.json"
        f.write_text(json.dumps({"env": "dev", "keep": 1}))
        result = parse_inputs(("env=prod",), str(f))
        assert result == {"env": "prod", "keep": 1}

    def test_flag_adds_new_key_to_file_inputs(self, tmp_path):
        f = tmp_path / "inputs.yaml"
        f.write_text("a: 1\n")
        result = parse_inputs(("b=2",), str(f))
        assert result == {"a": 1, "b": 2}

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises((FileNotFoundError, OSError)):
            parse_inputs((), str(tmp_path / "does-not-exist.json"))
