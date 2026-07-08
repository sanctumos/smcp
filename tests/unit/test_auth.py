"""
Unit tests for the HTTP-transport authentication feature (issue #39):
AuthConfig, resolve_auth_config, header extraction, is_authorized, and the
AuthMiddleware ASGI behavior. Targets 100% of the new auth code.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import sys
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))
_spec = importlib.util.spec_from_file_location("smcp_module", str(_repo_root / "smcp.py"))
smcp_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smcp_module)

AuthConfig = smcp_module.AuthConfig
resolve_auth_config = smcp_module.resolve_auth_config
is_authorized = smcp_module.is_authorized
_extract_presented_key = smcp_module._extract_presented_key
_env_truthy = smcp_module._env_truthy
AuthMiddleware = smcp_module.AuthMiddleware


_AUTH_ENVS = ("MCP_API_KEY", "MCP_API_KEYS", "MCP_AUTH_DISABLED", "MCP_AUTH_ALLOW_LOOPBACK")


@pytest.fixture
def clean_auth_env(monkeypatch):
    for k in _AUTH_ENVS:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


@pytest.mark.unit
class TestEnvTruthy:
    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "Yes", "on"])
    def test_truthy(self, val):
        assert _env_truthy(val) is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "", "  ", None, "nope"])
    def test_falsy(self, val):
        assert _env_truthy(val) is False


@pytest.mark.unit
class TestResolveAuthConfig:
    def test_no_config(self, clean_auth_env):
        cfg = resolve_auth_config()
        assert cfg.keys == frozenset()
        assert cfg.enforce is False
        assert cfg.disabled is False
        assert cfg.allow_loopback is True

    def test_single_key(self, clean_auth_env):
        clean_auth_env.setenv("MCP_API_KEY", "s3cret")
        cfg = resolve_auth_config()
        assert cfg.keys == frozenset({"s3cret"})
        assert cfg.enforce is True

    def test_multiple_keys_merge_and_trim(self, clean_auth_env):
        clean_auth_env.setenv("MCP_API_KEY", "primary")
        clean_auth_env.setenv("MCP_API_KEYS", " a , b ,, c ")
        cfg = resolve_auth_config()
        assert cfg.keys == frozenset({"primary", "a", "b", "c"})

    def test_disabled_disables_enforce(self, clean_auth_env):
        clean_auth_env.setenv("MCP_API_KEY", "x")
        clean_auth_env.setenv("MCP_AUTH_DISABLED", "1")
        cfg = resolve_auth_config()
        assert cfg.disabled is True
        assert cfg.enforce is False

    def test_allow_loopback_env_override(self, clean_auth_env):
        clean_auth_env.setenv("MCP_API_KEY", "x")
        clean_auth_env.setenv("MCP_AUTH_ALLOW_LOOPBACK", "0")
        cfg = resolve_auth_config()
        assert cfg.allow_loopback is False

    def test_require_auth_forces_loopback_off(self, clean_auth_env):
        clean_auth_env.setenv("MCP_API_KEY", "x")
        clean_auth_env.setenv("MCP_AUTH_ALLOW_LOOPBACK", "1")
        cfg = resolve_auth_config(require_auth=True)
        assert cfg.allow_loopback is False

    def test_empty_key_values_ignored(self, clean_auth_env):
        clean_auth_env.setenv("MCP_API_KEY", "   ")
        clean_auth_env.setenv("MCP_API_KEYS", " , , ")
        cfg = resolve_auth_config()
        assert cfg.keys == frozenset()
        assert cfg.enforce is False


@pytest.mark.unit
class TestAuthConfigEnforce:
    def test_enforce_true(self):
        assert AuthConfig(frozenset({"k"}), True, False).enforce is True

    def test_enforce_false_no_keys(self):
        assert AuthConfig(frozenset(), True, False).enforce is False

    def test_enforce_false_disabled(self):
        assert AuthConfig(frozenset({"k"}), True, True).enforce is False


@pytest.mark.unit
class TestExtractPresentedKey:
    def test_bearer(self):
        assert _extract_presented_key({"authorization": "Bearer abc123"}) == "abc123"

    def test_bearer_case_insensitive_scheme(self):
        assert _extract_presented_key({"authorization": "bearer abc"}) == "abc"

    def test_bearer_empty_token_falls_through(self):
        assert _extract_presented_key({"authorization": "Bearer   "}) is None

    def test_non_bearer_scheme_ignored(self):
        assert _extract_presented_key({"authorization": "Basic Zm9v"}) is None

    def test_x_api_key(self):
        assert _extract_presented_key({"x-api-key": "k9"}) == "k9"

    def test_bearer_takes_precedence(self):
        headers = {"authorization": "Bearer top", "x-api-key": "other"}
        assert _extract_presented_key(headers) == "top"

    def test_none_when_absent(self):
        assert _extract_presented_key({}) is None

    def test_x_api_key_blank_ignored(self):
        assert _extract_presented_key({"x-api-key": "   "}) is None


@pytest.mark.unit
class TestIsAuthorized:
    def _cfg(self, keys=("good",), allow_loopback=True, disabled=False):
        return AuthConfig(frozenset(keys), allow_loopback, disabled)

    def test_not_enforced_allows_all(self):
        cfg = AuthConfig(frozenset(), True, False)
        assert is_authorized({}, "8.8.8.8", cfg) is True

    def test_loopback_bypass(self):
        assert is_authorized({}, "127.0.0.1", self._cfg()) is True

    def test_loopback_bypass_ipv6(self):
        assert is_authorized({}, "::1", self._cfg()) is True

    def test_loopback_disabled_requires_key(self):
        cfg = self._cfg(allow_loopback=False)
        assert is_authorized({}, "127.0.0.1", cfg) is False
        assert is_authorized({"authorization": "Bearer good"}, "127.0.0.1", cfg) is True

    def test_valid_bearer_remote(self):
        assert is_authorized({"authorization": "Bearer good"}, "8.8.8.8", self._cfg()) is True

    def test_valid_x_api_key_remote(self):
        assert is_authorized({"x-api-key": "good"}, "8.8.8.8", self._cfg()) is True

    def test_wrong_key_remote(self):
        assert is_authorized({"authorization": "Bearer bad"}, "8.8.8.8", self._cfg()) is False

    def test_missing_key_remote(self):
        assert is_authorized({}, "8.8.8.8", self._cfg()) is False

    def test_multi_key_accepts_any(self):
        cfg = self._cfg(keys=("k1", "k2", "k3"))
        assert is_authorized({"x-api-key": "k3"}, "8.8.8.8", cfg) is True


# --- AuthMiddleware (direct ASGI harness) ----------------------------------

class _RecordApp:
    def __init__(self):
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


async def _drive(mw, scope):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    await mw(scope, receive, send)
    return sent


def _http_scope(headers=None, client=("8.8.8.8", 5555)):
    return {
        "type": "http",
        "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()],
        "client": client,
    }


@pytest.mark.unit
class TestAuthMiddleware:
    async def test_non_http_scope_passthrough(self):
        app = _RecordApp()
        mw = AuthMiddleware(app, AuthConfig(frozenset({"k"}), True, False))
        await _drive(mw, {"type": "lifespan"})
        assert app.called is True

    async def test_not_enforced_passthrough(self):
        app = _RecordApp()
        mw = AuthMiddleware(app, AuthConfig(frozenset(), True, False))
        await _drive(mw, _http_scope())
        assert app.called is True

    async def test_authorized_bearer_passthrough(self):
        app = _RecordApp()
        mw = AuthMiddleware(app, AuthConfig(frozenset({"k"}), False, False))
        await _drive(mw, _http_scope({"authorization": "Bearer k"}))
        assert app.called is True

    async def test_unauthorized_returns_401(self):
        app = _RecordApp()
        mw = AuthMiddleware(app, AuthConfig(frozenset({"k"}), False, False))
        sent = await _drive(mw, _http_scope({"authorization": "Bearer wrong"}))
        assert app.called is False
        start = sent[0]
        assert start["status"] == 401
        header_names = {name for name, _ in start["headers"]}
        assert b"www-authenticate" in header_names
        assert sent[1]["body"] == b'{"error":"unauthorized"}'

    async def test_loopback_client_bypass(self):
        app = _RecordApp()
        mw = AuthMiddleware(app, AuthConfig(frozenset({"k"}), True, False))
        await _drive(mw, _http_scope(client=("127.0.0.1", 1)))
        assert app.called is True

    async def test_missing_client_treated_as_remote(self):
        app = _RecordApp()
        mw = AuthMiddleware(app, AuthConfig(frozenset({"k"}), True, False))
        sent = await _drive(mw, _http_scope(client=None))
        assert app.called is False
        assert sent[0]["status"] == 401
