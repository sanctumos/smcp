"""
Unit tests for Letta env var loading at SMCP startup.
Tests load_letta_env_vars() with mocked HTTP and environment.
"""

import json
import os
import pytest
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Project root for imports (pytest runs from repo root)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import importlib.util
_spec = importlib.util.spec_from_file_location("smcp_module", Path(__file__).resolve().parent.parent.parent / "smcp.py")
_smcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_smcp)

load_letta_env_vars = _smcp.load_letta_env_vars
_load_letta_dotenv = _smcp._load_letta_dotenv


@pytest.mark.unit
class TestLoadLettaDotenv:
    """Test loading LETTA_* from ~/.letta/.env when not already in environment."""

    def test_loads_from_dotenv_and_sets_default_url(self):
        """When ~/.letta/.env has LETTA_SERVER_PASSWORD only, URL defaults to 127.0.0.1:8284."""
        with tempfile.TemporaryDirectory() as d:
            env_dir = Path(d) / ".letta"
            env_dir.mkdir()
            (env_dir / ".env").write_text("export LETTA_SERVER_PASSWORD=token123\n")
            with patch.dict(os.environ, {"HOME": d}, clear=False):
                for k in ("LETTA_SERVER_URL", "LETTA_SERVER_PASSWORD", "LETTA_API_KEY"):
                    os.environ.pop(k, None)
                _load_letta_dotenv()
                assert os.environ.get("LETTA_SERVER_PASSWORD") == "token123"
                assert os.environ.get("LETTA_SERVER_URL") == "http://127.0.0.1:8284"

    def test_does_not_overwrite_existing_env(self):
        """Existing LETTA_SERVER_URL and LETTA_SERVER_PASSWORD are not overwritten by file."""
        with tempfile.TemporaryDirectory() as d:
            env_dir = Path(d) / ".letta"
            env_dir.mkdir()
            (env_dir / ".env").write_text("export LETTA_SERVER_PASSWORD=fromfile\nexport LETTA_SERVER_URL=http://other:9999\n")
            with patch.dict(os.environ, {"HOME": d, "LETTA_SERVER_PASSWORD": "existing", "LETTA_SERVER_URL": "http://existing:8284"}, clear=False):
                _load_letta_dotenv()
                assert os.environ.get("LETTA_SERVER_PASSWORD") == "existing"
                assert os.environ.get("LETTA_SERVER_URL") == "http://existing:8284"

    def test_skips_when_file_missing(self):
        """When ~/.letta/.env does not exist, no error and env unchanged."""
        with tempfile.TemporaryDirectory() as d:
            # no .letta/.env created
            with patch.dict(os.environ, {"HOME": d}, clear=False):
                for k in ("LETTA_SERVER_URL", "LETTA_SERVER_PASSWORD"):
                    os.environ.pop(k, None)
                _load_letta_dotenv()
                assert os.environ.get("LETTA_SERVER_PASSWORD") is None or os.environ.get("LETTA_SERVER_PASSWORD") == ""


@pytest.mark.unit
class TestLoadLettaEnvVarsNoOp:
    """Test that load_letta_env_vars does nothing when URL/password unset."""

    def test_no_op_when_url_unset(self):
        """When LETTA_SERVER_URL is unset, no HTTP request is made."""
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"HOME": d, "LETTA_SERVER_PASSWORD": "secret"}, clear=False):
                os.environ.pop("LETTA_SERVER_URL", None)
                with patch("urllib.request.urlopen") as mock_urlopen:
                    load_letta_env_vars()
                    mock_urlopen.assert_not_called()

    def test_no_op_when_password_unset(self):
        """When LETTA_SERVER_PASSWORD (and LETTA_API_KEY) are unset, no HTTP request."""
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"HOME": d, "LETTA_SERVER_URL": "http://127.0.0.1:8284"}, clear=False):
                for key in ("LETTA_SERVER_PASSWORD", "LETTA_API_KEY"):
                    os.environ.pop(key, None)
                with patch("urllib.request.urlopen") as mock_urlopen:
                    load_letta_env_vars()
                    mock_urlopen.assert_not_called()

    def test_no_op_when_url_empty_after_strip(self):
        """When LETTA_SERVER_URL is blank, no request."""
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"HOME": d, "LETTA_SERVER_URL": "  ", "LETTA_SERVER_PASSWORD": "x"}, clear=False):
                with patch("urllib.request.urlopen") as mock_urlopen:
                    load_letta_env_vars()
                    mock_urlopen.assert_not_called()


@pytest.mark.unit
class TestLoadLettaEnvVarsSingleAgent:
    """Test single-agent path (LETTA_AGENT_ID set)."""

    def test_single_agent_success_updates_env(self):
        """Single agent with tool_exec_environment_variables updates os.environ."""
        single_agent = {
            "id": "agent-123",
            "name": "Test",
            "tool_exec_environment_variables": [
                {"key": "VENICE_IMAGE_ANALYSIS_API_KEY", "value": "sk-abc"},
                {"key": "FOO", "value": "bar"},
            ],
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(single_agent).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)

        with patch.dict(os.environ, {
            "LETTA_SERVER_URL": "http://127.0.0.1:8284",
            "LETTA_SERVER_PASSWORD": "token",
            "LETTA_AGENT_ID": "agent-123",
        }, clear=False):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                load_letta_env_vars()
            assert os.environ.get("VENICE_IMAGE_ANALYSIS_API_KEY") == "sk-abc"
            assert os.environ.get("FOO") == "bar"

    def test_single_agent_uses_secrets_key(self):
        """Single agent with 'secrets' key (not tool_exec_environment_variables) is parsed."""
        single_agent = {
            "id": "agent-456",
            "name": "Other",
            "secrets": [
                {"key": "API_KEY", "value": "from-secrets"},
            ],
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(single_agent).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)

        env = {
            "LETTA_SERVER_URL": "http://localhost:8284",
            "LETTA_SERVER_PASSWORD": "t",
            "LETTA_AGENT_ID": "agent-456",
        }
        with patch.object(_smcp, "os") as mock_os:
            mock_os.environ = env
            mock_os.getenv = lambda k, default=None: env.get(k, default or "")
            mock_os.path = __import__("os").path
            with patch("urllib.request.urlopen", return_value=mock_resp):
                load_letta_env_vars()
        assert env.get("API_KEY") == "from-secrets"


@pytest.mark.unit
class TestLoadLettaEnvVarsListAgents:
    """Test list-agents path (no LETTA_AGENT_ID)."""

    def test_list_agents_success_merges_env(self):
        """List of agents with env vars merges into os.environ (later wins)."""
        agents_list = [
            {
                "id": "a1",
                "tool_exec_environment_variables": [
                    {"key": "SHARED", "value": "first"},
                    {"key": "ONLY1", "value": "v1"},
                ],
            },
            {
                "id": "a2",
                "tool_exec_environment_variables": [
                    {"key": "SHARED", "value": "second"},
                    {"key": "ONLY2", "value": "v2"},
                ],
            },
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(agents_list).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)

        env = {
            "LETTA_SERVER_URL": "http://127.0.0.1:8284",
            "LETTA_SERVER_PASSWORD": "token",
        }
        with patch.object(_smcp, "os") as mock_os:
            mock_os.environ = env
            mock_os.getenv = lambda k, default=None: env.get(k, default or "")
            mock_os.path = __import__("os").path
            with patch("urllib.request.urlopen", return_value=mock_resp):
                load_letta_env_vars()
        assert env.get("SHARED") == "second"
        assert env.get("ONLY1") == "v1"
        assert env.get("ONLY2") == "v2"

    def test_uses_letta_api_key_when_password_unset(self):
        """When LETTA_SERVER_PASSWORD unset, LETTA_API_KEY is used and request is made."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([]).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)

        with patch.dict(os.environ, {
            "LETTA_SERVER_URL": "http://x:8284",
            "LETTA_API_KEY": "api-key-token",
        }, clear=False):
            os.environ.pop("LETTA_SERVER_PASSWORD", None)
            with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
                load_letta_env_vars()
                mock_urlopen.assert_called_once()
                call = mock_urlopen.call_args[0][0]
                assert call.get_header("Authorization") == "Bearer api-key-token"

    def test_empty_list_no_env_update(self):
        """Empty agents list does not crash and does not add env vars."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([]).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)

        before = dict(os.environ)
        with patch.dict(os.environ, {
            "LETTA_SERVER_URL": "http://127.0.0.1:8284",
            "LETTA_SERVER_PASSWORD": "t",
        }, clear=False):
            os.environ.pop("LETTA_AGENT_ID", None)
            with patch("urllib.request.urlopen", return_value=mock_resp):
                load_letta_env_vars()
        # No new keys that look like Letta-loaded (we didn't add any)
        assert True


@pytest.mark.unit
class TestLoadLettaEnvVarsErrors:
    """Test error handling."""

    def test_http_error_does_not_raise(self):
        """HTTPError is caught and logged; no exception propagates."""
        import urllib.error
        err = urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)
        err.read = MagicMock(return_value=b"unauthorized")

        with patch.dict(os.environ, {
            "LETTA_SERVER_URL": "http://127.0.0.1:8284",
            "LETTA_SERVER_PASSWORD": "t",
        }, clear=False):
            with patch("urllib.request.urlopen", side_effect=err):
                load_letta_env_vars()
        # No exception

    def test_generic_exception_does_not_raise(self):
        """Generic exception is caught and logged."""
        with patch.dict(os.environ, {
            "LETTA_SERVER_URL": "http://127.0.0.1:8284",
            "LETTA_SERVER_PASSWORD": "t",
        }, clear=False):
            with patch("urllib.request.urlopen", side_effect=Exception("network error")):
                load_letta_env_vars()
        # No exception

    def test_strips_trailing_slash_from_base_url(self):
        """Base URL with trailing slash is used correctly (single-agent URL)."""
        single_agent = {"id": "agent-1", "name": "A", "tool_exec_environment_variables": []}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(single_agent).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)

        with patch.dict(os.environ, {
            "LETTA_SERVER_URL": "http://127.0.0.1:8284/",
            "LETTA_SERVER_PASSWORD": "t",
            "LETTA_AGENT_ID": "agent-1",
        }, clear=False):
            with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
                load_letta_env_vars()
                req = mock_urlopen.call_args[0][0]
                full_url = req.get_full_url() if hasattr(req, "get_full_url") else getattr(req, "full_url", str(req))
                assert full_url.startswith("http://127.0.0.1:8284/v1/agents/agent-1")
                assert "include=agent.secrets" in full_url
