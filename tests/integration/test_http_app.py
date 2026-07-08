"""
Integration tests for the HTTP/SSE Starlette app and the async_main
orchestration in smcp.py, exercised through a real ASGI transport.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import sys
import os
import importlib.util
import contextlib
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import httpx
import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))
_spec = importlib.util.spec_from_file_location("smcp_module", str(_repo_root / "smcp.py"))
smcp_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = smcp_module
_spec.loader.exec_module(smcp_module)


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class _FakeSseTransport:
    """Minimal stand-in for SseServerTransport for route wiring tests."""

    def __init__(self):
        self.connected = False

    @contextlib.asynccontextmanager
    async def connect_sse(self, scope, receive, send):
        self.connected = True
        yield ("read_stream", "write_stream")

    async def handle_post_message(self, scope, receive, send):
        # Minimal ASGI app for the /messages/ mount
        from starlette.responses import Response
        await Response("ok", status_code=202)(scope, receive, send)


@pytest.mark.integration
class TestBuildAppRoutes:
    async def test_post_sse_with_body_returns_400(self):
        app = smcp_module.build_app(_FakeSseTransport())
        async with _client(app) as c:
            r = await c.post("/sse", content=b'{"jsonrpc":"2.0"}')
        assert r.status_code == 400
        assert "/messages/" in r.text

    async def test_post_sse_empty_returns_400(self):
        app = smcp_module.build_app(_FakeSseTransport())
        async with _client(app) as c:
            r = await c.post("/sse", content=b"")
        assert r.status_code == 400
        assert "Empty POST" in r.text

    async def test_get_sse_runs_server_over_stream(self):
        fake_transport = _FakeSseTransport()
        fake_server = MagicMock()
        fake_server.run = AsyncMock(return_value=None)
        fake_server.create_initialization_options = MagicMock(return_value={})
        app = smcp_module.build_app(fake_transport)
        with patch.object(smcp_module._default_ctx, "server", fake_server):
            async with _client(app) as c:
                r = await c.get("/sse")
        assert r.status_code == 200
        assert fake_transport.connected is True
        fake_server.run.assert_awaited_once()

    async def test_messages_mount_reachable(self):
        app = smcp_module.build_app(_FakeSseTransport())
        async with _client(app) as c:
            r = await c.post("/messages/", content=b"{}")
        assert r.status_code == 202

    async def test_get_sse_returns_503_when_server_uninitialized(self):
        ctx = smcp_module.ServerContext.create()
        ctx.server = None
        app = smcp_module.build_app(_FakeSseTransport(), ctx=ctx)
        async with _client(app) as c:
            r = await c.get("/sse")
        assert r.status_code == 503
        assert "not initialized" in r.text

    async def test_post_sse_body_read_error_returns_500(self):
        """If reading the request body raises, the /sse shim returns 500."""
        app = smcp_module.build_app(_FakeSseTransport())
        sent = []

        async def receive():
            raise RuntimeError("broken stream")

        async def send(msg):
            sent.append(msg)

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "path": "/sse",
            "raw_path": b"/sse",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 5555),
            "server": ("test", 80),
            "scheme": "http",
        }
        await app(scope, receive, send)
        status = next(m["status"] for m in sent if m["type"] == "http.response.start")
        assert status == 500


@pytest.mark.integration
class TestAsyncMainOrchestration:
    async def test_async_main_wires_and_serves_and_signal_handler(self):
        fake_server_instance = MagicMock()
        fake_server_instance.serve = AsyncMock(return_value=None)
        fake_server_instance.should_exit = False

        captured_handlers = {}

        def fake_signal(signum, handler):
            captured_handlers[signum] = handler

        with patch.object(sys, "argv", ["smcp.py", "--port", "8123"]), \
             patch.object(smcp_module, "load_letta_env_vars", lambda: None), \
             patch.object(smcp_module, "register_plugin_tools", lambda s, ctx=None: None), \
             patch("uvicorn.Config", MagicMock()), \
             patch("uvicorn.Server", MagicMock(return_value=fake_server_instance)), \
             patch("signal.signal", fake_signal):
            await smcp_module.async_main()

        fake_server_instance.serve.assert_awaited_once()
        # Exercise the registered signal handler -> flips should_exit.
        assert captured_handlers, "no signal handlers registered"
        handler = next(iter(captured_handlers.values()))
        handler(2, None)
        assert fake_server_instance.should_exit is True

    def test_main_invokes_async_main(self):
        with patch.object(smcp_module, "async_main", new=AsyncMock(return_value=None)) as m:
            smcp_module.main()
        m.assert_awaited_once()

    async def test_async_main_refuses_external_bind_without_auth(self):
        with patch.object(sys, "argv", ["smcp.py", "--allow-external"]), \
             patch.object(smcp_module, "load_letta_env_vars", lambda: None), \
             patch.dict("os.environ", {}, clear=False):
            os.environ.pop("MCP_API_KEY", None)
            os.environ.pop("MCP_API_KEYS", None)
            os.environ.pop("MCP_AUTH_DISABLED", None)
            with pytest.raises(SystemExit) as ei:
                await smcp_module.async_main()
        assert ei.value.code == 2

    async def test_async_main_allows_external_bind_when_auth_disabled(self):
        fake_server_instance = MagicMock()
        fake_server_instance.serve = AsyncMock(return_value=None)
        fake_server_instance.should_exit = False

        with patch.object(sys, "argv", ["smcp.py", "--allow-external"]), \
             patch.object(smcp_module, "load_letta_env_vars", lambda: None), \
             patch.object(smcp_module, "register_plugin_tools", lambda s, ctx=None: None), \
             patch.dict(os.environ, {"MCP_AUTH_DISABLED": "1"}, clear=False), \
             patch("uvicorn.Config", MagicMock()), \
             patch("uvicorn.Server", MagicMock(return_value=fake_server_instance)), \
             patch("signal.signal", MagicMock()):
            await smcp_module.async_main()
        fake_server_instance.serve.assert_awaited_once()
