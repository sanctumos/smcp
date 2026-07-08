"""
Unit tests for smcp.py server internals that were previously uncovered:
plugin tool execution (real subprocess), argument parsing, host resolution,
server/app construction, tool handlers, and Letta env loading branches.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import asyncio
import json
import os
import sys
import types
import importlib.util
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

# Load smcp.py as an isolated module (same pattern as test_mcp_server.py)
_here = Path(__file__).resolve()
_repo_root = _here.parent.parent.parent
sys.path.insert(0, str(_repo_root))
_spec = importlib.util.spec_from_file_location("smcp_module", str(_repo_root / "smcp.py"))
smcp_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = smcp_module
_spec.loader.exec_module(smcp_module)


# --- helpers ---------------------------------------------------------------

_PLUGIN_CLI = '''#!/usr/bin/env python3
import argparse, json, sys

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command")

    echo = sub.add_parser("echo")
    echo.add_argument("--name")
    echo.add_argument("--flag", action="store_true")
    echo.add_argument("--tag", action="append")

    sub.add_parser("failjson")
    sub.add_parser("failraw")
    sub.add_parser("silentfail")

    args = p.parse_args()
    if args.command == "echo":
        print(json.dumps({"name": args.name, "flag": args.flag, "tag": args.tag}))
        sys.exit(0)
    if args.command == "failjson":
        print(json.dumps({"error": "boom-json"})); sys.exit(1)
    if args.command == "failraw":
        print("raw failure text"); sys.exit(1)
    if args.command == "silentfail":
        sys.exit(3)
    print(json.dumps({"error": "unknown"})); sys.exit(1)

if __name__ == "__main__":
    main()
'''


@pytest.fixture
def real_plugin(tmp_path):
    """Create a real plugin CLI on disk and register it; yields plugin name."""
    plug_dir = tmp_path / "plugins" / "toy"
    plug_dir.mkdir(parents=True)
    cli = plug_dir / "cli.py"
    cli.write_text(_PLUGIN_CLI)
    os.chmod(cli, 0o755)
    with patch.object(smcp_module, "plugin_registry", {"toy": {"path": str(cli), "commands": {}}}):
        yield "toy"


# --- execute_plugin_tool (real subprocess) ---------------------------------

@pytest.mark.unit
class TestExecutePluginToolReal:
    async def test_success_scalar_and_list_args(self, real_plugin):
        # Boolean rendering is covered in test_bool_args.py (schema-aware, #37/#38).
        result = await smcp_module.execute_plugin_tool(
            "toy__echo", {"name": "abc", "tag": ["a", "b"]}
        )
        data = json.loads(result)
        assert data["name"] == "abc"
        assert data["tag"] == ["a", "b"]

    async def test_error_json_stdout(self, real_plugin):
        with pytest.raises(smcp_module.ToolError) as ei:
            await smcp_module.execute_plugin_tool("toy__failjson", {})
        assert "boom-json" in ei.value.message
        assert ei.value.code == "plugin_error"

    async def test_error_raw_stdout(self, real_plugin):
        with pytest.raises(smcp_module.ToolError) as ei:
            await smcp_module.execute_plugin_tool("toy__failraw", {})
        assert "raw failure text" in ei.value.message

    async def test_error_no_output(self, real_plugin):
        with pytest.raises(smcp_module.ToolError) as ei:
            await smcp_module.execute_plugin_tool("toy__silentfail", {})
        assert "exited with code 3" in ei.value.message

    async def test_legacy_dot_separator(self, real_plugin):
        result = await smcp_module.execute_plugin_tool("toy.echo", {"name": "dot"})
        assert json.loads(result)["name"] == "dot"

    async def test_no_separator_invalid(self):
        with pytest.raises(smcp_module.ToolError) as ei:
            await smcp_module.execute_plugin_tool("noseparator", {})
        assert "Invalid tool name format" in ei.value.message
        assert ei.value.code == "invalid_tool_name"

    async def test_timeout_path(self, real_plugin):
        """Force the outer timeout handler by making wait_for raise TimeoutError."""
        async def fake_wait_for(aw, timeout):
            # Cancel the underlying coroutine and simulate a timeout
            if asyncio.iscoroutine(aw):
                aw.close()
            raise asyncio.TimeoutError()

        # A configured timeout is required for the wait_for path to be taken.
        with patch.dict(os.environ, {"MCP_PLUGIN_TIMEOUT": "5"}), \
             patch.object(smcp_module.asyncio, "wait_for", side_effect=fake_wait_for):
            with pytest.raises(smcp_module.ToolError) as ei:
                await smcp_module.execute_plugin_tool("toy__echo", {"name": "x"})
        assert "timed out" in ei.value.message
        assert ei.value.code == "timeout"


# --- parse_arguments / resolve_host / create_server ------------------------

@pytest.mark.unit
class TestArgsHostServer:
    def test_parse_arguments_defaults(self):
        with patch.object(sys, "argv", ["smcp.py"]):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("MCP_PORT", None)
                os.environ.pop("MCP_HOST", None)
                args = smcp_module.parse_arguments()
        assert args.port == 8000
        assert args.host == "127.0.0.1"
        assert args.allow_external is False

    def test_parse_arguments_custom(self):
        with patch.object(sys, "argv", ["smcp.py", "--allow-external", "--port", "9100", "--host", "0.0.0.0"]):
            args = smcp_module.parse_arguments()
        assert args.allow_external is True
        assert args.port == 9100
        assert args.host == "0.0.0.0"

    def test_parse_arguments_env_defaults(self):
        with patch.object(sys, "argv", ["smcp.py"]):
            with patch.dict(os.environ, {"MCP_PORT": "7777", "MCP_HOST": "1.2.3.4"}):
                args = smcp_module.parse_arguments()
        assert args.port == 7777
        assert args.host == "1.2.3.4"

    def test_resolve_host_external(self):
        args = types.SimpleNamespace(allow_external=True, host="127.0.0.1")
        assert smcp_module.resolve_host(args) == "0.0.0.0"

    def test_resolve_host_localhost(self):
        args = types.SimpleNamespace(allow_external=False, host="127.0.0.1")
        assert smcp_module.resolve_host(args) == "127.0.0.1"

    def test_resolve_host_explicit_nonlocal(self):
        args = types.SimpleNamespace(allow_external=False, host="10.0.0.5")
        assert smcp_module.resolve_host(args) == "10.0.0.5"

    def test_create_server(self):
        srv = smcp_module.create_server()
        assert srv is not None
        assert srv.name == "sanctum-letta-mcp"
        # #49: reports the real package version, not a hardcoded "1.0.0".
        assert srv.version == smcp_module._package_version()
        assert srv.version != "1.0.0"

    def test_package_version_source_run(self):
        # #50: from a non-installed source tree, _package_version falls back to
        # the module-level __version__ literal (importlib.metadata has no dist).
        import importlib.metadata as _md
        with patch.object(_md, "version", side_effect=_md.PackageNotFoundError):
            assert smcp_module._package_version() == smcp_module.__version__

    def test_package_version_installed(self):
        # #50: when installed, the reported version comes from distribution
        # metadata so it matches the actually-installed wheel.
        import importlib.metadata as _md
        with patch.object(_md, "version", return_value="9.9.9"):
            assert smcp_module._package_version() == "9.9.9"

    def test_get_plugin_help_exception(self):
        with patch.object(smcp_module.subprocess, "run", side_effect=OSError("spawn fail")):
            assert smcp_module.get_plugin_help("toy", "/x/cli.py") == ""

    def test_discover_plugins_default_path(self, monkeypatch):
        """No MCP_PLUGINS_DIR -> falls back to the bundled plugins directory."""
        monkeypatch.delenv("MCP_PLUGINS_DIR", raising=False)
        plugins = smcp_module.discover_plugins()
        # The repo ships demo plugins; at minimum this must not error and returns a dict.
        assert isinstance(plugins, dict)


# --- register_plugin_tools handlers + connect/disconnect skip --------------

@pytest.mark.unit
class TestRegisterHandlers:
    async def test_handlers_and_connect_skip(self):
        real_server = smcp_module.create_server()
        describe = {
            "plugin": {"name": "toy", "version": "1.0.0"},
            "commands": [
                {"name": "connect", "parameters": []},      # should be skipped
                {"name": "disconnect", "parameters": []},   # should be skipped
                {"name": "echo", "description": "Echo", "parameters": []},
            ],
        }
        with patch.object(smcp_module, "discover_plugins", return_value={"toy": {"path": "/x/cli.py"}}), \
             patch.object(smcp_module, "get_plugin_describe", return_value=describe):
            smcp_module.register_plugin_tools(real_server)

        # list_tools handler registered -> exercise it
        list_handler = real_server.request_handlers
        # Call the registered handlers through the captured closures instead:
        # re-register with capture to call directly
        captured = {}

        class CapSrv:
            def list_tools(self):
                def deco(fn):
                    captured["list"] = fn
                    return fn
                return deco

            def call_tool(self):
                def deco(fn):
                    captured["call"] = fn
                    return fn
                return deco

        with patch.object(smcp_module, "discover_plugins", return_value={"toy": {"path": "/x/cli.py"}}), \
             patch.object(smcp_module, "get_plugin_describe", return_value=describe):
            smcp_module.register_plugin_tools(CapSrv())

        tools = await captured["list"]()
        names = [t.name for t in tools]
        assert "toy__echo" in names
        assert "toy__connect" not in names
        assert "toy__disconnect" not in names

        # call_tool handler success -> normal content (isError=False)
        with patch.object(smcp_module, "execute_plugin_tool", new=AsyncMock(return_value="ok-result")):
            out = await captured["call"]("toy__echo", {})
        assert out[0].text == "ok-result"

        # call_tool handler unexpected error -> structured CallToolResult(isError=True)
        with patch.object(smcp_module, "execute_plugin_tool", new=AsyncMock(side_effect=RuntimeError("bad"))):
            out = await captured["call"]("toy__echo", {})
        assert isinstance(out, smcp_module.CallToolResult)
        assert out.isError is True
        assert "Tool execution failed" in out.content[0].text
        assert out.structuredContent["error"]["code"] == "internal_error"

        # call_tool handler structured ToolError -> code preserved
        with patch.object(
            smcp_module, "execute_plugin_tool",
            new=AsyncMock(side_effect=smcp_module.ToolError("plugin_error", "boom")),
        ):
            out = await captured["call"]("toy__echo", {})
        assert isinstance(out, smcp_module.CallToolResult)
        assert out.isError is True
        assert out.structuredContent["error"]["code"] == "plugin_error"
        assert out.content[0].text == "boom"


# --- Letta env loading extra branches --------------------------------------

@pytest.mark.unit
class TestLettaEnvBranches:
    def test_dotenv_parsing_branches(self, tmp_path, monkeypatch):
        home = tmp_path
        letta_dir = home / ".letta"
        letta_dir.mkdir()
        env_file = letta_dir / ".env"
        env_file.write_text(
            "# a comment\n"
            "\n"
            "notexport LINE=ignored\n"
            "export MALFORMED\n"
            "export LETTA_SERVER_PASSWORD=\"secretpw\"\n"
        )
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(home) if p == "~" else p)
        for k in ("LETTA_SERVER_URL", "LETTA_SERVER_PASSWORD", "LETTA_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        smcp_module._load_letta_dotenv()
        assert os.environ.get("LETTA_SERVER_PASSWORD") == "secretpw"
        # URL default set because password present and no URL
        assert os.environ.get("LETTA_SERVER_URL") == "http://127.0.0.1:8284"

    def test_load_letta_env_vars_no_creds_returns(self, monkeypatch):
        for k in ("LETTA_SERVER_URL", "LETTA_SERVER_PASSWORD", "LETTA_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setattr(smcp_module, "_load_letta_dotenv", lambda: None)
        # Should simply return without error
        smcp_module.load_letta_env_vars()

    def test_load_letta_env_vars_merges(self, monkeypatch):
        monkeypatch.setattr(smcp_module, "_load_letta_dotenv", lambda: None)
        monkeypatch.setenv("LETTA_SERVER_URL", "http://127.0.0.1:8284")
        monkeypatch.setenv("LETTA_SERVER_PASSWORD", "pw")
        monkeypatch.delenv("LETTA_AGENT_ID", raising=False)

        agents = [{"id": "agent-1", "secrets": [{"key": "FOO", "value": "bar"}],
                   "tool_exec_environment_variables": [{"key": "BAZ", "value": "qux"}]}]

        class FakeResp:
            def __init__(self, payload): self._p = payload
            def read(self): return json.dumps(self._p).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with patch.object(smcp_module.urllib.request, "urlopen", return_value=FakeResp(agents)):
            monkeypatch.delenv("FOO", raising=False)
            monkeypatch.delenv("BAZ", raising=False)
            smcp_module.load_letta_env_vars()
        assert os.environ.get("FOO") == "bar"
        assert os.environ.get("BAZ") == "qux"

    def test_load_letta_env_vars_non_list_response(self, monkeypatch):
        monkeypatch.setattr(smcp_module, "_load_letta_dotenv", lambda: None)
        monkeypatch.setenv("LETTA_SERVER_URL", "http://127.0.0.1:8284")
        monkeypatch.setenv("LETTA_SERVER_PASSWORD", "pw")
        monkeypatch.delenv("LETTA_AGENT_ID", raising=False)

        class FakeResp:
            def read(self): return json.dumps({"not": "a list"}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with patch.object(smcp_module.urllib.request, "urlopen", return_value=FakeResp()):
            smcp_module.load_letta_env_vars()  # should handle gracefully
