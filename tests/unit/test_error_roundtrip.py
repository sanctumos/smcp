"""
Plugin error round-tripping on nonzero exit (issue #42, mirrors AnimusUNO #8).

Verifies execute_plugin_tool propagates structured JSON errors written to stdout
(plugins commonly print {"error": ...} and exit 1) and never returns an empty
error message.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

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


# Plugin that prints to stdout and exits nonzero in several shapes.
_CLI = '''#!/usr/bin/env python3
import json, sys

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "ok":
        print(json.dumps({"result": "done"})); sys.exit(0)
    if cmd == "errjson":
        print(json.dumps({"error": "specific plugin failure"})); sys.exit(1)
    if cmd == "errjson_nokey":
        print(json.dumps({"detail": "no error key here"})); sys.exit(1)
    if cmd == "errraw":
        print("plain text failure"); sys.exit(2)
    if cmd == "errsilent":
        sys.exit(4)
    print(json.dumps({"error": "unknown"})); sys.exit(1)

if __name__ == "__main__":
    main()
'''


@pytest.fixture
def err_plugin(tmp_path):
    plug_dir = tmp_path / "plugins" / "errp"
    plug_dir.mkdir(parents=True)
    cli = plug_dir / "cli.py"
    cli.write_text(_CLI)
    os.chmod(cli, 0o755)
    registry = {"errp": {"path": str(cli), "commands": {}}}
    with patch.object(smcp_module, "plugin_registry", registry):
        yield "errp"


@pytest.mark.unit
class TestErrorRoundTrip:
    async def test_structured_json_error_round_trips(self, err_plugin):
        with pytest.raises(smcp_module.ToolError) as ei:
            await smcp_module.execute_plugin_tool("errp__errjson", {})
        assert "specific plugin failure" in ei.value.message
        assert ei.value.code == "plugin_error"

    async def test_json_without_error_key_returns_raw(self, err_plugin):
        with pytest.raises(smcp_module.ToolError) as ei:
            await smcp_module.execute_plugin_tool("errp__errjson_nokey", {})
        assert "no error key here" in ei.value.message

    async def test_raw_text_error_not_empty(self, err_plugin):
        with pytest.raises(smcp_module.ToolError) as ei:
            await smcp_module.execute_plugin_tool("errp__errraw", {})
        assert "plain text failure" in ei.value.message
        assert ei.value.message.strip() != ""

    async def test_no_output_falls_back_to_code_not_empty(self, err_plugin):
        with pytest.raises(smcp_module.ToolError) as ei:
            await smcp_module.execute_plugin_tool("errp__errsilent", {})
        assert "exited with code 4" in ei.value.message
        assert ei.value.code == "plugin_error"

    async def test_success_passthrough(self, err_plugin):
        result = await smcp_module.execute_plugin_tool("errp__ok", {})
        assert "done" in result
