"""
Logging configuration is explicit, not an import side effect (issue #52).

Importing smcp.py must not create directories or attach handlers to the root
logger. Logging is wired only when the server starts via configure_logging(),
which is idempotent and honors a configurable log directory.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import logging
import os
import subprocess
import sys
import textwrap
import importlib.util
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))
_spec = importlib.util.spec_from_file_location("smcp_module", str(_repo_root / "smcp.py"))
smcp_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = smcp_module
_spec.loader.exec_module(smcp_module)


@pytest.fixture
def clean_logging():
    """Isolate root-logger state and the module's configured flag."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    prev_flag = smcp_module._logging_configured
    smcp_module._logging_configured = False
    try:
        yield
    finally:
        for h in root.handlers[:]:
            if h not in saved_handlers:
                root.removeHandler(h)
        root.setLevel(saved_level)
        smcp_module._logging_configured = prev_flag


@pytest.mark.unit
class TestConfigureLogging:
    def test_no_setup_logging_symbol(self):
        # The import-time side-effect function is gone.
        assert not hasattr(smcp_module, "setup_logging")

    def test_creates_dir_and_handlers(self, tmp_path, clean_logging):
        target = tmp_path / "mylogs"
        smcp_module.configure_logging(str(target))
        assert target.is_dir()
        root = logging.getLogger()
        assert any(
            isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers
        )

    def test_idempotent(self, tmp_path, clean_logging):
        smcp_module.configure_logging(str(tmp_path / "l"))
        n = len(logging.getLogger().handlers)
        smcp_module.configure_logging(str(tmp_path / "l"))
        assert len(logging.getLogger().handlers) == n

    def test_env_dir_used(self, tmp_path, clean_logging, monkeypatch):
        target = tmp_path / "envlogs"
        monkeypatch.setenv("MCP_LOG_DIR", str(target))
        smcp_module.configure_logging()
        assert target.is_dir()

    def test_arg_overrides_env(self, tmp_path, clean_logging, monkeypatch):
        monkeypatch.setenv("MCP_LOG_DIR", str(tmp_path / "env"))
        explicit = tmp_path / "explicit"
        smcp_module.configure_logging(str(explicit))
        assert explicit.is_dir()
        assert not (tmp_path / "env").exists()


@pytest.mark.unit
def test_import_is_side_effect_free(tmp_path):
    """Loading smcp.py in a fresh interpreter must not create logs/ or touch root."""
    code = textwrap.dedent(
        """
        import os, sys, logging, importlib.util
        os.chdir(sys.argv[1])
        sys.path.insert(0, sys.argv[2])
        before = list(logging.getLogger().handlers)
        spec = importlib.util.spec_from_file_location("smcp_probe", sys.argv[3])
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m
        spec.loader.exec_module(m)
        after = list(logging.getLogger().handlers)
        assert not os.path.exists("logs"), "import created logs/ dir"
        assert after == before, "import added root handlers"
        print("SIDE_EFFECT_FREE_OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path), str(_repo_root), str(_repo_root / "smcp.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "SIDE_EFFECT_FREE_OK" in result.stdout
    assert not (tmp_path / "logs").exists()
