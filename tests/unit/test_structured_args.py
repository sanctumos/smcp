"""
Schema-aware structured (array/object) tool-argument rendering (issue #56).

Verifies that execute_plugin_tool serializes array/object tool arguments to a
plugin's argv as clean JSON, and normalizes Letta's single-child ``{"item": ...}``
array encoding centrally, so plugins receive real JSON arrays instead of Python
``repr`` strings or mangled wrappers.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import json
import os
import sys
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

_here = Path(__file__).resolve()
_repo_root = _here.parent.parent.parent
sys.path.insert(0, str(_repo_root))
_spec = importlib.util.spec_from_file_location("smcp_module", str(_repo_root / "smcp.py"))
smcp_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = smcp_module
_spec.loader.exec_module(smcp_module)

render = smcp_module._render_tool_argument
unwrap = smcp_module._unwrap_item_array
dtype = smcp_module._arg_declared_type


# --- _arg_declared_type ----------------------------------------------------

@pytest.mark.unit
class TestDeclaredType:
    def test_none(self):
        assert dtype(None) == ""

    def test_empty(self):
        assert dtype({}) == ""

    def test_lowercased_and_stripped(self):
        assert dtype({"type": "  Array "}) == "array"


# --- _unwrap_item_array ----------------------------------------------------

@pytest.mark.unit
class TestUnwrapItemArray:
    def test_list_passthrough(self):
        assert unwrap([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]

    def test_item_wrapping_single_object(self):
        assert unwrap({"item": {"a": 1}}) == [{"a": 1}]

    def test_item_wrapping_list(self):
        assert unwrap({"item": [{"a": 1}, {"a": 2}]}) == [{"a": 1}, {"a": 2}]

    def test_plain_dict_becomes_single_element(self):
        assert unwrap({"display_name": "x"}) == [{"display_name": "x"}]

    def test_scalar_becomes_single_element(self):
        assert unwrap("x") == ["x"]

    def test_dict_with_item_and_other_keys_is_not_unwrapped(self):
        # Ambiguous: an object that legitimately has an "item" field is kept whole.
        val = {"item": 1, "qty": 2}
        assert unwrap(val) == [val]


# --- _render_tool_argument -------------------------------------------------

@pytest.mark.unit
class TestRenderToolArgument:
    def test_bool_value_style_default(self):
        assert render("flag", True, None) == ["--flag", "true"]
        assert render("flag", False, None) == ["--flag", "false"]

    def test_bool_flag_style(self):
        spec = {"action": "store_true"}
        assert render("v", True, spec) == ["--v"]
        assert render("v", False, spec) == []

    def test_declared_array_of_objects_is_json(self):
        out = render("recipients", [{"display_name": "A", "lines": [{"menu_item_id": 1}]}],
                     {"type": "array"})
        assert out[0] == "--recipients"
        assert json.loads(out[1]) == [{"display_name": "A", "lines": [{"menu_item_id": 1}]}]

    def test_declared_array_item_wrapper_single(self):
        out = render("recipients", {"item": {"display_name": "A"}}, {"type": "array"})
        assert json.loads(out[1]) == [{"display_name": "A"}]

    def test_declared_array_item_wrapper_list(self):
        out = render("recipients", {"item": [{"x": 1}, {"x": 2}]}, {"type": "array"})
        assert json.loads(out[1]) == [{"x": 1}, {"x": 2}]

    def test_declared_array_string_passthrough(self):
        # Already-serialized JSON string is passed untouched (plugin json.loads it).
        out = render("recipients", '[{"x":1}]', {"type": "array"})
        assert out == ["--recipients", '[{"x":1}]']

    def test_declared_object_dict_is_json(self):
        out = render("cfg", {"a": 1, "b": [2, 3]}, {"type": "object"})
        assert out[0] == "--cfg"
        assert json.loads(out[1]) == {"a": 1, "b": [2, 3]}

    def test_declared_object_scalar_is_str(self):
        assert render("cfg", "raw", {"type": "object"}) == ["--cfg", "raw"]

    def test_undeclared_dict_is_json(self):
        out = render("payload", {"a": 1}, None)
        assert json.loads(out[1]) == {"a": 1}

    def test_undeclared_list_of_objects_is_json(self):
        # The pre-fix bug: this used to become repeated --x "{'a': 1}" (Python repr).
        out = render("x", [{"a": 1}, {"a": 2}], None)
        assert out[0] == "--x"
        assert json.loads(out[1]) == [{"a": 1}, {"a": 2}]

    def test_undeclared_scalar_list_is_repeated(self):
        # Backward-compatible with argparse nargs / action=append.
        assert render("tag", ["a", "b"], None) == ["--tag", "a", "--tag", "b"]

    def test_scalar_value(self):
        assert render("name", "abc", None) == ["--name", "abc"]

    def test_scalar_int(self):
        assert render("n", 5, None) == ["--n", "5"]


# --- end-to-end through a real plugin subprocess ---------------------------

_DESCRIBE = {
    "plugin": {"name": "structy", "version": "1.0.0", "description": "structured args"},
    "commands": [
        {
            "name": "echo",
            "description": "parse json args and echo them back",
            "parameters": [
                {"name": "name", "type": "string"},
                {"name": "recipients", "type": "array"},
                {"name": "config", "type": "object"},
            ],
        }
    ],
}

_PLUGIN_CLI = '''#!/usr/bin/env python3
import argparse, json, sys

DESCRIBE = ''' + json.dumps(_DESCRIBE) + '''

def main():
    if "--describe" in sys.argv[1:]:
        print(json.dumps(DESCRIBE)); sys.exit(0)
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command")
    echo = sub.add_parser("echo")
    echo.add_argument("--name")
    echo.add_argument("--recipients")   # JSON array string
    echo.add_argument("--config")       # JSON object string
    args = p.parse_args()
    if args.command == "echo":
        out = {"name": args.name}
        out["recipients"] = json.loads(args.recipients) if args.recipients else None
        out["config"] = json.loads(args.config) if args.config else None
        print(json.dumps(out)); sys.exit(0)
    print(json.dumps({"error": "unknown"})); sys.exit(1)

if __name__ == "__main__":
    main()
'''


@pytest.fixture
def structy_plugin(tmp_path):
    plug_dir = tmp_path / "plugins" / "structy"
    plug_dir.mkdir(parents=True)
    cli = plug_dir / "cli.py"
    cli.write_text(_PLUGIN_CLI)
    os.chmod(cli, 0o755)
    registry = {
        "structy": {"path": str(cli), "commands": {"echo": _DESCRIBE["commands"][0]}}
    }
    with patch.object(smcp_module, "plugin_registry", registry):
        yield "structy"


@pytest.mark.integration
class TestStructuredRoundTrip:
    async def test_recipients_array_of_objects(self, structy_plugin):
        payload = [{"display_name": "Soni", "lines": [{"menu_item_id": 12, "quantity": 2}]}]
        result = await smcp_module.execute_plugin_tool(
            "structy__echo", {"name": "x", "recipients": payload}
        )
        assert json.loads(result)["recipients"] == payload

    async def test_recipients_item_wrapper_normalized(self, structy_plugin):
        # Letta single-child coercion -> a clean 1-element array reaches the plugin.
        result = await smcp_module.execute_plugin_tool(
            "structy__echo",
            {"name": "x", "recipients": {"item": {"display_name": "Soni", "lines": []}}},
        )
        assert json.loads(result)["recipients"] == [{"display_name": "Soni", "lines": []}]

    async def test_config_object(self, structy_plugin):
        result = await smcp_module.execute_plugin_tool(
            "structy__echo", {"name": "x", "config": {"fee": 5, "flags": [1, 2]}}
        )
        assert json.loads(result)["config"] == {"fee": 5, "flags": [1, 2]}

    async def test_recipients_string_passthrough(self, structy_plugin):
        result = await smcp_module.execute_plugin_tool(
            "structy__echo", {"name": "x", "recipients": '[{"display_name":"Soni"}]'}
        )
        assert json.loads(result)["recipients"] == [{"display_name": "Soni"}]
