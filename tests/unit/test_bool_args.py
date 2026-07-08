"""
Schema-aware boolean argument rendering (issues #37 and #38).

Verifies that execute_plugin_tool renders boolean tool arguments onto plugin
argv according to each parameter's --describe declaration:

- value-style (default / action=store): ``--name true|false`` always (#37)
- flag-style (action=store_true/store_false): bare ``--name`` only when true (#38)

and that register_plugin_tools caches the command spec that drives this.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import asyncio
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


# A plugin whose argparse matches its --describe declaration for each style.
_DESCRIBE = {
    "plugin": {"name": "toy2", "version": "1.0.0", "description": "bool styles"},
    "commands": [
        {
            "name": "echo",
            "description": "echo args back as JSON",
            "parameters": [
                {"name": "name", "type": "string"},
                # value-style boolean (no action declared -> default value-style)
                {"name": "is-available", "type": "boolean"},
                # flag-style: store_true
                {"name": "verbose", "type": "boolean", "action": "store_true"},
                # flag-style: store_false (inverted --no-* flag)
                {"name": "no-cache", "type": "boolean", "action": "store_false"},
                # array
                {"name": "tag", "type": "array"},
            ],
        }
    ],
}

_PLUGIN_CLI = '''#!/usr/bin/env python3
import argparse, json, sys

DESCRIBE = ''' + json.dumps(_DESCRIBE) + '''

def main():
    if "--describe" in sys.argv[1:]:
        print(json.dumps(DESCRIBE))
        sys.exit(0)
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command")
    echo = sub.add_parser("echo")
    echo.add_argument("--name")
    echo.add_argument("--is-available")  # value-style: accepts a string token
    echo.add_argument("--verbose", action="store_true")
    echo.add_argument("--no-cache", action="store_false", dest="cache")
    echo.add_argument("--tag", action="append")
    args = p.parse_args()
    if args.command == "echo":
        print(json.dumps({
            "name": args.name,
            "is_available": args.is_available,
            "verbose": args.verbose,
            "cache": args.cache,
            "tag": args.tag,
        }))
        sys.exit(0)
    print(json.dumps({"error": "unknown"})); sys.exit(1)

if __name__ == "__main__":
    main()
'''


@pytest.fixture
def toy2_plugin(tmp_path):
    """Real plugin CLI on disk, registered with its cached --describe command spec."""
    plug_dir = tmp_path / "plugins" / "toy2"
    plug_dir.mkdir(parents=True)
    cli = plug_dir / "cli.py"
    cli.write_text(_PLUGIN_CLI)
    os.chmod(cli, 0o755)
    registry = {
        "toy2": {
            "path": str(cli),
            # command spec cached exactly as register_plugin_tools would store it
            "commands": {"echo": _DESCRIBE["commands"][0]},
        }
    }
    with patch.object(smcp_module, "plugin_registry", registry):
        yield "toy2"


# --- helper unit tests -----------------------------------------------------

@pytest.mark.unit
class TestBooleanStyleHelper:
    def test_none_spec_defaults_value_style(self):
        assert smcp_module._boolean_is_flag_style(None) is False

    def test_empty_spec_defaults_value_style(self):
        assert smcp_module._boolean_is_flag_style({}) is False

    def test_store_true_is_flag_style(self):
        assert smcp_module._boolean_is_flag_style({"action": "store_true"}) is True

    def test_store_false_is_flag_style(self):
        assert smcp_module._boolean_is_flag_style({"action": "STORE_FALSE"}) is True

    def test_action_store_is_value_style(self):
        assert smcp_module._boolean_is_flag_style({"action": "store"}) is False

    def test_arg_style_flag(self):
        assert smcp_module._boolean_is_flag_style({"arg_style": "flag"}) is True

    def test_arg_style_value(self):
        assert smcp_module._boolean_is_flag_style({"arg_style": "value"}) is False

    def test_takes_value_false_is_flag_style(self):
        assert smcp_module._boolean_is_flag_style({"takes_value": False}) is True

    def test_takes_value_true_is_value_style(self):
        assert smcp_module._boolean_is_flag_style({"takes_value": True}) is False


@pytest.mark.unit
class TestCommandParamSpecs:
    def test_missing_plugin_returns_empty(self):
        with patch.object(smcp_module, "plugin_registry", {}):
            assert smcp_module._command_param_specs("nope", "echo") == {}

    def test_missing_commands_returns_empty(self):
        with patch.object(smcp_module, "plugin_registry", {"p": {"path": "x"}}):
            assert smcp_module._command_param_specs("p", "echo") == {}

    def test_normalizes_underscore_names(self):
        registry = {
            "p": {"path": "x", "commands": {"echo": {"parameters": [
                {"name": "is_available", "type": "boolean"},
            ]}}}
        }
        with patch.object(smcp_module, "plugin_registry", registry):
            specs = smcp_module._command_param_specs("p", "echo")
        assert "is-available" in specs


# --- end-to-end rendering (real subprocess) --------------------------------

@pytest.mark.unit
class TestBooleanRendering:
    async def test_value_style_true(self, toy2_plugin):
        result = await smcp_module.execute_plugin_tool(
            "toy2__echo", {"name": "x", "is_available": True}
        )
        assert json.loads(result)["is_available"] == "true"

    async def test_value_style_false_reaches_argv(self, toy2_plugin):
        # #37: false must NOT be silently dropped.
        result = await smcp_module.execute_plugin_tool(
            "toy2__echo", {"name": "x", "is_available": False}
        )
        assert json.loads(result)["is_available"] == "false"

    async def test_flag_style_store_true_true_appends_flag(self, toy2_plugin):
        result = await smcp_module.execute_plugin_tool(
            "toy2__echo", {"name": "x", "verbose": True}
        )
        assert json.loads(result)["verbose"] is True

    async def test_flag_style_store_true_false_omits_flag(self, toy2_plugin):
        # #38: store_true flag with false must be omitted, not "--verbose false".
        result = await smcp_module.execute_plugin_tool(
            "toy2__echo", {"name": "x", "verbose": False}
        )
        assert json.loads(result)["verbose"] is False

    async def test_flag_style_store_false_true_appends_flag(self, toy2_plugin):
        # store_false: presence of --no-cache sets cache=False.
        result = await smcp_module.execute_plugin_tool(
            "toy2__echo", {"name": "x", "no_cache": True}
        )
        assert json.loads(result)["cache"] is False

    async def test_flag_style_store_false_false_omits_flag(self, toy2_plugin):
        # store_false with false -> omit -> cache stays default True.
        result = await smcp_module.execute_plugin_tool(
            "toy2__echo", {"name": "x", "no_cache": False}
        )
        assert json.loads(result)["cache"] is True

    async def test_scalar_and_list_still_render(self, toy2_plugin):
        result = await smcp_module.execute_plugin_tool(
            "toy2__echo", {"name": "abc", "tag": ["a", "b"]}
        )
        data = json.loads(result)
        assert data["name"] == "abc"
        assert data["tag"] == ["a", "b"]

    async def test_undeclared_bool_defaults_value_style(self, tmp_path):
        # A plugin discovered WITHOUT a cached spec falls back to value-style.
        plug_dir = tmp_path / "plugins" / "toy3"
        plug_dir.mkdir(parents=True)
        cli = plug_dir / "cli.py"
        cli.write_text(_PLUGIN_CLI)
        os.chmod(cli, 0o755)
        # commands empty -> no param spec -> value-style default
        registry = {"toy3": {"path": str(cli), "commands": {}}}
        with patch.object(smcp_module, "plugin_registry", registry):
            result = await smcp_module.execute_plugin_tool(
                "toy3__echo", {"name": "x", "is_available": False}
            )
        assert json.loads(result)["is_available"] == "false"


# --- argument alias coalescing (merged from master; overlaps #9) -----------

@pytest.mark.unit
class TestCoalesceAliases:
    def test_non_dict_returned_as_is(self):
        assert smcp_module._coalesce_tool_argument_aliases("nope") == "nope"

    def test_prefers_underscore_when_both_present(self):
        out = smcp_module._coalesce_tool_argument_aliases(
            {"payload_json": "{}", "payload-json": "{}"}
        )
        assert "payload-json" not in out and out["payload_json"] == "{}"

    def test_renames_hyphen_to_underscore(self):
        out = smcp_module._coalesce_tool_argument_aliases({"payload-json": "{}"})
        assert out == {"payload_json": "{}"}

    def test_catering_invoice_id_aliases(self):
        assert smcp_module._coalesce_tool_argument_aliases(
            {"catering_invoice_id": 1, "catering-invoice-id": 1}
        ) == {"catering_invoice_id": 1}
        assert smcp_module._coalesce_tool_argument_aliases(
            {"catering-invoice-id": 2}
        ) == {"catering_invoice_id": 2}

    def test_invoice_command_aliases(self):
        assert smcp_module._coalesce_tool_argument_aliases(
            {"invoice_command": "x", "invoice-command": "x"}
        ) == {"invoice_command": "x"}
        assert smcp_module._coalesce_tool_argument_aliases(
            {"invoice-command": "y"}
        ) == {"invoice_command": "y"}

    def test_generic_arbitrary_key_no_product_literals(self):
        # #44: coalescing is generic — arbitrary hyphenated params normalize too.
        assert smcp_module._coalesce_tool_argument_aliases(
            {"some-random-flag": "v"}
        ) == {"some_random_flag": "v"}

    def test_first_nonnull_variant_wins(self):
        assert smcp_module._coalesce_tool_argument_aliases(
            {"foo_bar": "a", "foo-bar": "b"}
        ) == {"foo_bar": "a"}

    def test_null_variant_filled_by_nonnull(self):
        assert smcp_module._coalesce_tool_argument_aliases(
            {"foo_bar": None, "foo-bar": "v"}
        ) == {"foo_bar": "v"}

    def test_core_has_no_product_specific_literals(self):
        # Guard: the coalescer must not name any product field (issue #44).
        import inspect
        src = inspect.getsource(smcp_module._coalesce_tool_argument_aliases)
        for literal in ("payload_json", "catering_invoice_id", "invoice_command"):
            assert literal not in src


# --- registration caches the command spec ----------------------------------

@pytest.mark.unit
class TestRegistrationCachesSpec:
    async def test_register_plugin_tools_caches_command_spec(self, tmp_path):
        plug_dir = tmp_path / "plugins" / "toy2"
        plug_dir.mkdir(parents=True)
        cli = plug_dir / "cli.py"
        cli.write_text(_PLUGIN_CLI)
        os.chmod(cli, 0o755)

        class _CapSrv:
            def list_tools(self):
                return lambda f: f
            def call_tool(self):
                return lambda f: f

        with patch.dict(os.environ, {"MCP_PLUGINS_DIR": str(tmp_path / "plugins")}):
            smcp_module.register_plugin_tools(_CapSrv())

        cached = smcp_module.plugin_registry["toy2"]["commands"]["echo"]
        names = {p["name"] for p in cached["parameters"]}
        assert "verbose" in names and "is-available" in names
