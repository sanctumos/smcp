"""
Configurable plugin subprocess timeout (issue #41, mirrors AnimusUNO #10).

Covers _resolve_plugin_timeout, the --plugin-timeout CLI flag and its precedence
wiring in async_main, and that the default (no timeout) path skips asyncio.wait_for.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import asyncio
import json
import os
import sys
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

_here = Path(__file__).resolve()
_repo_root = _here.parent.parent.parent
sys.path.insert(0, str(_repo_root))
_spec = importlib.util.spec_from_file_location("smcp_module", str(_repo_root / "smcp.py"))
smcp_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = smcp_module
_spec.loader.exec_module(smcp_module)


_ECHO_CLI = '''#!/usr/bin/env python3
import argparse, json, sys
def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command")
    echo = sub.add_parser("echo")
    echo.add_argument("--name")
    args = p.parse_args()
    if args.command == "echo":
        print(json.dumps({"name": args.name})); sys.exit(0)
    sys.exit(1)
if __name__ == "__main__":
    main()
'''


@pytest.fixture(autouse=True)
def _clear_timeout_env():
    old = os.environ.pop("MCP_PLUGIN_TIMEOUT", None)
    yield
    os.environ.pop("MCP_PLUGIN_TIMEOUT", None)
    if old is not None:
        os.environ["MCP_PLUGIN_TIMEOUT"] = old


@pytest.mark.unit
class TestResolvePluginTimeout:
    def test_unset_is_none(self):
        assert smcp_module._resolve_plugin_timeout() is None

    def test_empty_is_none(self):
        with patch.dict(os.environ, {"MCP_PLUGIN_TIMEOUT": "  "}):
            assert smcp_module._resolve_plugin_timeout() is None

    def test_zero_is_none(self):
        with patch.dict(os.environ, {"MCP_PLUGIN_TIMEOUT": "0"}):
            assert smcp_module._resolve_plugin_timeout() is None

    def test_negative_is_none(self):
        with patch.dict(os.environ, {"MCP_PLUGIN_TIMEOUT": "-5"}):
            assert smcp_module._resolve_plugin_timeout() is None

    def test_invalid_is_none(self):
        with patch.dict(os.environ, {"MCP_PLUGIN_TIMEOUT": "abc"}):
            assert smcp_module._resolve_plugin_timeout() is None

    def test_float_value(self):
        with patch.dict(os.environ, {"MCP_PLUGIN_TIMEOUT": "12.5"}):
            assert smcp_module._resolve_plugin_timeout() == 12.5

    def test_int_value(self):
        with patch.dict(os.environ, {"MCP_PLUGIN_TIMEOUT": "300"}):
            assert smcp_module._resolve_plugin_timeout() == 300.0


@pytest.mark.unit
class TestNoTimeoutPathSkipsWaitFor:
    async def test_default_does_not_call_wait_for(self, tmp_path):
        plug_dir = tmp_path / "plugins" / "toy"
        plug_dir.mkdir(parents=True)
        cli = plug_dir / "cli.py"
        cli.write_text(_ECHO_CLI)
        os.chmod(cli, 0o755)
        registry = {"toy": {"path": str(cli), "commands": {}}}

        def _boom(*a, **k):
            raise AssertionError("wait_for should not be used with no timeout")

        with patch.object(smcp_module, "plugin_registry", registry), \
             patch.object(smcp_module.asyncio, "wait_for", side_effect=_boom):
            result = await smcp_module.execute_plugin_tool("toy__echo", {"name": "ok"})
        assert json.loads(result)["name"] == "ok"


@pytest.mark.unit
class TestPluginTimeoutCli:
    def test_default_flag_is_none(self):
        with patch.object(sys, "argv", ["smcp.py"]):
            args = smcp_module.parse_arguments()
        assert args.plugin_timeout is None

    def test_flag_parsed(self):
        with patch.object(sys, "argv", ["smcp.py", "--plugin-timeout", "30"]):
            args = smcp_module.parse_arguments()
        assert args.plugin_timeout == 30.0


@pytest.mark.integration
class TestAsyncMainWiring:
    async def test_flag_sets_env(self):
        fake_instance = MagicMock()
        fake_instance.serve = AsyncMock(return_value=None)
        fake_instance.should_exit = False
        with patch.object(sys, "argv", ["smcp.py", "--plugin-timeout", "45"]), \
             patch.object(smcp_module, "load_letta_env_vars", lambda: None), \
             patch.object(smcp_module, "register_plugin_tools", lambda s, ctx=None: None), \
             patch("uvicorn.Config", MagicMock()), \
             patch("uvicorn.Server", MagicMock(return_value=fake_instance)), \
             patch("signal.signal", MagicMock()):
            await smcp_module.async_main()
        assert os.environ.get("MCP_PLUGIN_TIMEOUT") == "45.0"
