"""
Plugin ``--describe`` contract: versioned schema + validation (issue #47).

Covers:
- the in-core validator ``validate_describe_contract`` (field-addressed errors),
- discovery-time enforcement (malformed describe -> plugin skipped with an
  actionable log, valid describe -> tools registered),
- conformance of the bundled demo plugins against the published JSON Schema
  (docs/plugin-contract/v1.json) and the in-core validator.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import json
import os
import sys
import subprocess
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_here = Path(__file__).resolve()
_repo_root = _here.parent.parent.parent
sys.path.insert(0, str(_repo_root))
_spec = importlib.util.spec_from_file_location("smcp_module", str(_repo_root / "smcp.py"))
smcp_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = smcp_module
_spec.loader.exec_module(smcp_module)

validate = smcp_module.validate_describe_contract

CONTRACT_SCHEMA_PATH = _repo_root / "docs" / "plugin-contract" / "v1.json"
DEMO_MATH_CLI = _repo_root / "plugins" / "demo_math" / "cli.py"
DEMO_TEXT_CLI = _repo_root / "plugins" / "demo_text" / "cli.py"


def _valid_spec():
    return {
        "contract_version": "1.0",
        "plugin": {"name": "toy", "version": "1.0.0", "description": "d"},
        "commands": [
            {
                "name": "do-thing",
                "description": "does a thing",
                "parameters": [
                    {"name": "a", "type": "string", "required": True, "description": "x"},
                    {"name": "b", "type": "number", "required": False},
                    {"name": "c", "type": "array"},
                ],
            }
        ],
    }


# --- validator: happy paths -------------------------------------------------

@pytest.mark.unit
class TestValidatorValid:
    def test_full_valid_spec(self):
        assert validate(_valid_spec()) == []

    def test_contract_version_optional(self):
        spec = _valid_spec()
        del spec["contract_version"]
        assert validate(spec) == []

    def test_plugin_optional(self):
        spec = _valid_spec()
        del spec["plugin"]
        assert validate(spec) == []

    def test_parameters_optional(self):
        spec = {"commands": [{"name": "noargs"}]}
        assert validate(spec) == []

    def test_patch_version_accepted(self):
        spec = _valid_spec()
        spec["contract_version"] = "1.4.2"
        assert validate(spec) == []


# --- validator: field-addressed errors --------------------------------------

@pytest.mark.unit
class TestValidatorErrors:
    def test_non_dict_payload(self):
        errs = validate(["not", "an", "object"])
        assert errs and "must be a JSON object" in errs[0]

    def test_missing_commands(self):
        errs = validate({"plugin": {"name": "x"}})
        assert any("missing required 'commands'" in e for e in errs)

    def test_commands_not_array(self):
        errs = validate({"commands": {"nope": 1}})
        assert any("'commands' must be an array" in e for e in errs)

    def test_wrong_contract_major(self):
        spec = _valid_spec()
        spec["contract_version"] = "2.0"
        errs = validate(spec)
        assert any("unsupported contract_version" in e for e in errs)

    def test_contract_version_wrong_type(self):
        spec = _valid_spec()
        spec["contract_version"] = 1.0
        errs = validate(spec)
        assert any("contract_version must be a string" in e for e in errs)

    def test_command_missing_name(self):
        errs = validate({"commands": [{"description": "no name"}]})
        assert any("commands[0].name is required" in e for e in errs)

    def test_command_name_bad_chars(self):
        errs = validate({"commands": [{"name": "bad name!"}]})
        assert any("commands[0].name" in e and "^[a-zA-Z0-9_-]+$" in e for e in errs)

    def test_command_not_object(self):
        errs = validate({"commands": ["nope"]})
        assert any("commands[0] must be an object" in e for e in errs)

    def test_param_bad_type(self):
        spec = _valid_spec()
        spec["commands"][0]["parameters"][0]["type"] = "str"
        errs = validate(spec)
        assert any("parameters[0].type 'str' is not one of" in e for e in errs)

    def test_param_missing_name(self):
        spec = _valid_spec()
        spec["commands"][0]["parameters"][0] = {"type": "string"}
        errs = validate(spec)
        assert any("parameters[0].name is required" in e for e in errs)

    def test_param_required_not_bool(self):
        spec = _valid_spec()
        spec["commands"][0]["parameters"][0]["required"] = "yes"
        errs = validate(spec)
        assert any("parameters[0].required must be a boolean" in e for e in errs)

    def test_parameters_not_array(self):
        errs = validate({"commands": [{"name": "c", "parameters": {"a": 1}}]})
        assert any("parameters must be an array" in e for e in errs)

    def test_plugin_not_object(self):
        errs = validate({"plugin": "nope", "commands": [{"name": "c"}]})
        assert any("plugin must be an object" in e for e in errs)

    def test_plugin_name_empty(self):
        errs = validate({"plugin": {"name": "  "}, "commands": [{"name": "c"}]})
        assert any("plugin.name must be a non-empty string" in e for e in errs)

    def test_command_name_empty(self):
        errs = validate({"commands": [{"name": ""}]})
        assert any("commands[0].name must be a non-empty string" in e for e in errs)

    def test_command_description_not_string(self):
        errs = validate({"commands": [{"name": "c", "description": 5}]})
        assert any("commands[0].description must be a string" in e for e in errs)

    def test_param_not_object(self):
        errs = validate({"commands": [{"name": "c", "parameters": [123]}]})
        assert any("parameters[0] must be an object" in e for e in errs)

    def test_param_name_empty(self):
        errs = validate({"commands": [{"name": "c", "parameters": [{"name": " "}]}]})
        assert any("parameters[0].name must be a non-empty string" in e for e in errs)

    def test_param_description_not_string(self):
        spec = {"commands": [{"name": "c", "parameters": [{"name": "p", "description": 9}]}]}
        errs = validate(spec)
        assert any("parameters[0].description must be a string" in e for e in errs)


# --- discovery-time enforcement ---------------------------------------------

@pytest.mark.unit
class TestRegistrationEnforcement:
    def _server(self):
        srv = MagicMock()
        srv.list_tools = MagicMock(return_value=lambda f: f)
        srv.call_tool = MagicMock(return_value=lambda f: f)
        return srv

    def test_malformed_describe_skips_plugin(self, caplog):
        bad = {"commands": [{"name": "ok"}, {"name": "bad name!"}]}
        with patch.object(smcp_module, "discover_plugins",
                          return_value={"toy": {"path": "/x/cli.py"}}), \
             patch.object(smcp_module, "get_plugin_describe", return_value=bad):
            import logging
            with caplog.at_level(logging.ERROR):
                smcp_module.register_plugin_tools(self._server())
        # Plugin skipped: no commands cached for it.
        assert "commands" not in smcp_module.plugin_registry.get("toy", {})
        assert any("violates the --describe contract" in r.message for r in caplog.records)

    def test_valid_describe_registers(self):
        good = _valid_spec()
        with patch.object(smcp_module, "discover_plugins",
                          return_value={"toy": {"path": "/x/cli.py"}}), \
             patch.object(smcp_module, "get_plugin_describe", return_value=good):
            smcp_module.register_plugin_tools(self._server())
        assert "do-thing" in smcp_module.plugin_registry["toy"]["commands"]


# --- demo plugin conformance against the published schema -------------------

def _describe(cli: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(cli), "--describe"],
        cwd=str(_repo_root), capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.unit
class TestPublishedSchema:
    def test_schema_file_is_valid_json(self):
        json.loads(CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))

    @pytest.mark.parametrize("cli", [DEMO_MATH_CLI, DEMO_TEXT_CLI])
    def test_demo_conforms_to_in_core_validator(self, cli):
        assert validate(_describe(cli)) == []

    @pytest.mark.parametrize("cli", [DEMO_MATH_CLI, DEMO_TEXT_CLI])
    def test_demo_conforms_to_published_schema(self, cli):
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads(CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=_describe(cli), schema=schema)

    def test_malformed_rejected_by_published_schema(self):
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads(CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))
        bad = {"commands": [{"name": "c", "parameters": [{"name": "p", "type": "str"}]}]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)
