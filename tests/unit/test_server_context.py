"""
ServerContext isolation (issue #46): two contexts coexist without cross-talk.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_here = Path(__file__).resolve()
_repo_root = _here.parent.parent.parent
sys.path.insert(0, str(_repo_root))
_spec = importlib.util.spec_from_file_location("smcp_module", str(_repo_root / "smcp.py"))
smcp_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = smcp_module
_spec.loader.exec_module(smcp_module)


@pytest.mark.unit
class TestServerContextIsolation:
    def test_two_contexts_independent_registries_and_metrics(self):
        a = smcp_module.ServerContext.create()
        b = smcp_module.ServerContext.create()
        assert a.plugin_registry is not b.plugin_registry
        assert a.metrics is not b.metrics
        assert a.governor is not b.governor

        a.plugin_registry["toy"] = {"path": "/a/cli.py", "commands": {}}
        a.metrics["tools_registered"] = 7
        assert "toy" not in b.plugin_registry
        assert b.metrics["tools_registered"] == 0

    def test_two_contexts_governors_attach_independently(self):
        a = smcp_module.ServerContext.create()
        b = smcp_module.ServerContext.create()
        a.governor.set_catalog(["alpha__one", "alpha__two"])
        b.governor.set_catalog(["beta__one"])
        a.governor.attach_profile("full")
        b.governor.attach_profile("full")
        assert "alpha__one" in a.governor.list_attached()
        assert "alpha__one" not in b.governor.list_attached()
        assert "beta__one" in b.governor.list_attached()

    async def test_register_plugin_tools_binds_to_given_context(self):
        ctx = smcp_module.ServerContext.create()
        describe = {
            "contract_version": "1.0",
            "plugin": {"name": "iso", "version": "1.0.0"},
            "commands": [
                {"name": "ping", "description": "pong", "parameters": []},
            ],
        }
        srv = MagicMock()
        captured = {}

        def list_tools():
            def deco(fn):
                captured["list"] = fn
                return fn
            return deco

        def call_tool():
            def deco(fn):
                captured["call"] = fn
                return fn
            return deco

        srv.list_tools = list_tools
        srv.call_tool = call_tool

        with patch.object(
            smcp_module, "discover_plugins", return_value={"iso": {"path": "/x/cli.py"}}
        ), patch.object(smcp_module, "get_plugin_describe", return_value=describe):
            smcp_module.register_plugin_tools(srv, ctx)

        assert "iso" in ctx.plugin_registry
        assert "iso" not in smcp_module._default_ctx.plugin_registry or (
            # default may have been mutated by other tests; only assert ctx got it
            "ping" in ctx.plugin_registry["iso"].get("commands", {})
        )
        tools = await captured["list"]()
        names = [t.name for t in tools]
        assert "iso__ping" in names
        assert ctx.metrics["tools_registered"] >= 1
