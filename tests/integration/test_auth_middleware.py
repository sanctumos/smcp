"""
Integration tests for HTTP-transport auth (issue #39): the wrapped ASGI app
served through httpx, build_app wrapping behavior, and the async_main
external-bind startup guard.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import sys
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

AuthConfig = smcp_module.AuthConfig
AuthMiddleware = smcp_module.AuthMiddleware


class _FakeSseTransport:
    @contextlib.asynccontextmanager
    async def connect_sse(self, scope, receive, send):
        yield ("r", "w")

    async def handle_post_message(self, scope, receive, send):
        from starlette.responses import Response
        await Response("ok", status_code=202)(scope, receive, send)


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


_AUTH_ENVS = ("MCP_API_KEY", "MCP_API_KEYS", "MCP_AUTH_DISABLED", "MCP_AUTH_ALLOW_LOOPBACK")


@pytest.fixture
def clean_auth_env(monkeypatch):
    for k in _AUTH_ENVS:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


@pytest.mark.integration
class TestBuildAppWrapping:
    def test_no_config_returns_starlette(self):
        from starlette.applications import Starlette
        app = smcp_module.build_app(_FakeSseTransport())
        assert isinstance(app, Starlette)

    def test_non_enforcing_config_returns_starlette(self):
        from starlette.applications import Starlette
        cfg = AuthConfig(frozenset(), True, False)  # no keys -> not enforcing
        app = smcp_module.build_app(_FakeSseTransport(), cfg)
        assert isinstance(app, Starlette)

    def test_enforcing_config_wraps_in_middleware(self):
        cfg = AuthConfig(frozenset({"k"}), False, False)
        app = smcp_module.build_app(_FakeSseTransport(), cfg)
        assert isinstance(app, AuthMiddleware)


@pytest.mark.integration
class TestWrappedAppOverHttp:
    def _app(self):
        # allow_loopback False so httpx's 127.0.0.1 client still needs a key
        cfg = AuthConfig(frozenset({"topsecret"}), False, False)
        return smcp_module.build_app(_FakeSseTransport(), cfg)

    async def test_missing_key_401(self):
        async with _client(self._app()) as c:
            r = await c.post("/sse", content=b'{"x":1}')
        assert r.status_code == 401
        assert r.headers.get("www-authenticate") == "Bearer"
        assert r.json()["error"] == "unauthorized"

    async def test_wrong_key_401(self):
        async with _client(self._app()) as c:
            r = await c.post("/sse", content=b'{"x":1}', headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401

    async def test_valid_bearer_reaches_route(self):
        async with _client(self._app()) as c:
            r = await c.post("/sse", content=b'{"x":1}', headers={"Authorization": "Bearer topsecret"})
        # Past auth -> hits the POST /sse shim (400), not 401
        assert r.status_code == 400
        assert "/messages/" in r.text

    async def test_valid_x_api_key_reaches_messages_mount(self):
        async with _client(self._app()) as c:
            r = await c.post("/messages/", content=b"{}", headers={"X-API-Key": "topsecret"})
        assert r.status_code == 202


@pytest.mark.integration
class TestAsyncMainAuthGuard:
    def _run_main(self):
        fake_instance = MagicMock()
        fake_instance.serve = AsyncMock(return_value=None)
        fake_instance.should_exit = False
        cm = (
            patch.object(smcp_module, "load_letta_env_vars", lambda: None),
            patch.object(smcp_module, "register_plugin_tools", lambda s: None),
            patch("uvicorn.Config", MagicMock()),
            patch("uvicorn.Server", MagicMock(return_value=fake_instance)),
            patch("signal.signal", MagicMock()),
        )
        return fake_instance, cm

    async def test_external_without_key_exits_2(self, clean_auth_env):
        fake_instance, cm = self._run_main()
        with patch.object(sys, "argv", ["smcp.py", "--allow-external"]):
            with cm[0], cm[1], cm[2], cm[3], cm[4]:
                with pytest.raises(SystemExit) as ei:
                    await smcp_module.async_main()
        assert ei.value.code == 2
        fake_instance.serve.assert_not_awaited()

    async def test_external_with_key_serves(self, clean_auth_env):
        clean_auth_env.setenv("MCP_API_KEY", "abc")
        fake_instance, cm = self._run_main()
        with patch.object(sys, "argv", ["smcp.py", "--allow-external"]):
            with cm[0], cm[1], cm[2], cm[3], cm[4]:
                await smcp_module.async_main()
        fake_instance.serve.assert_awaited_once()

    async def test_external_disabled_serves_open(self, clean_auth_env):
        clean_auth_env.setenv("MCP_AUTH_DISABLED", "1")
        fake_instance, cm = self._run_main()
        with patch.object(sys, "argv", ["smcp.py", "--allow-external"]):
            with cm[0], cm[1], cm[2], cm[3], cm[4]:
                await smcp_module.async_main()
        fake_instance.serve.assert_awaited_once()

    async def test_localhost_with_key_enforce_serves(self, clean_auth_env):
        clean_auth_env.setenv("MCP_API_KEY", "abc")
        fake_instance, cm = self._run_main()
        with patch.object(sys, "argv", ["smcp.py", "--require-auth"]):
            with cm[0], cm[1], cm[2], cm[3], cm[4]:
                await smcp_module.async_main()
        fake_instance.serve.assert_awaited_once()
