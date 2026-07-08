"""
Unit tests for smcp_stdio.py (the STDIO transport entry point), including
the graceful-shutdown and Windows stdout-flush ExceptionGroup handling.

The repo directory is itself named ``smcp`` and carries an ``__init__.py``,
so under pytest ``import smcp`` can resolve to the *package* rather than
``smcp.py``. smcp_stdio.py does a bare ``import smcp`` and needs the file
module (which defines ``logger``), so we load both modules from their file
paths inside a fixture and save/restore ``sys.modules`` to avoid disturbing
collection of the rest of the suite.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import sys
import contextlib
import importlib.util
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def stdio_mod():
    """Load smcp.py (as 'smcp') and smcp_stdio.py from file, isolated."""
    saved = {k: sys.modules.get(k) for k in ("smcp", "smcp_stdio")}
    try:
        smcp_spec = importlib.util.spec_from_file_location("smcp", str(_repo_root / "smcp.py"))
        smcp_file = importlib.util.module_from_spec(smcp_spec)
        sys.modules["smcp"] = smcp_file
        smcp_spec.loader.exec_module(smcp_file)

        stdio_spec = importlib.util.spec_from_file_location("smcp_stdio", str(_repo_root / "smcp_stdio.py"))
        stdio = importlib.util.module_from_spec(stdio_spec)
        sys.modules["smcp_stdio"] = stdio
        stdio_spec.loader.exec_module(stdio)
        yield stdio
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _fake_stdio_server():
    @contextlib.asynccontextmanager
    async def _cm():
        yield ("read_stream", "write_stream")
    return _cm()


def _fake_server(run_side_effect=None):
    srv = MagicMock()
    srv.create_initialization_options = MagicMock(return_value={})
    if run_side_effect is not None:
        srv.run = AsyncMock(side_effect=run_side_effect)
    else:
        srv.run = AsyncMock(return_value=None)
    return srv


@contextlib.contextmanager
def _patched(stdio_mod, *, run_side_effect=None, create_side_effect=None):
    srv = _fake_server(run_side_effect)
    create = MagicMock(side_effect=create_side_effect) if create_side_effect else MagicMock(return_value=srv)
    with patch.object(stdio_mod.smcp, "create_server", create), \
         patch.object(stdio_mod.smcp, "register_plugin_tools", MagicMock()), \
         patch("mcp.server.stdio.stdio_server", return_value=_fake_stdio_server()):
        yield srv


@pytest.mark.unit
class TestStdioEntry:
    async def test_happy_path(self, stdio_mod):
        with _patched(stdio_mod) as srv:
            await stdio_mod.main()
        srv.run.assert_awaited_once()

    async def test_init_failure_exits_1(self, stdio_mod):
        with _patched(stdio_mod, create_side_effect=RuntimeError("boom")):
            with pytest.raises(SystemExit) as ei:
                await stdio_mod.main()
        assert ei.value.code == 1

    async def test_keyboard_interrupt_is_graceful(self, stdio_mod):
        with _patched(stdio_mod, run_side_effect=KeyboardInterrupt()):
            await stdio_mod.main()  # must not raise

    async def test_generic_exception_exits_1(self, stdio_mod):
        with _patched(stdio_mod, run_side_effect=ValueError("nope")):
            with pytest.raises(SystemExit) as ei:
                await stdio_mod.main()
        assert ei.value.code == 1

    async def test_exceptiongroup_non_win32_reraises(self, stdio_mod):
        eg = ExceptionGroup("grp", [ValueError("x")])
        with _patched(stdio_mod, run_side_effect=eg), patch.object(sys, "platform", "linux"):
            with pytest.raises(SystemExit) as ei:
                await stdio_mod.main()
        assert ei.value.code == 1

    async def test_exceptiongroup_win32_flush_is_graceful(self, stdio_mod):
        eg = ExceptionGroup("grp", [OSError(22, "flush")])
        with _patched(stdio_mod, run_side_effect=eg), patch.object(sys, "platform", "win32"):
            await stdio_mod.main()  # all flush errors -> non-fatal

    async def test_base_exceptiongroup_win32_partial_reraises(self, stdio_mod):
        beg = BaseExceptionGroup("grp", [KeyboardInterrupt()])
        with _patched(stdio_mod, run_side_effect=beg), patch.object(sys, "platform", "win32"):
            with pytest.raises(BaseException):
                await stdio_mod.main()


@pytest.mark.unit
def test_import_time_stdout_handler_cleanup():
    """
    smcp_stdio, at import, must strip/redirect any stdout-bound StreamHandlers
    on both the root logger and smcp.logger so JSON-RPC stdout stays clean.
    We seed stdout handlers first, then load smcp_stdio and assert cleanup.
    """
    import logging
    saved = {k: sys.modules.get(k) for k in ("smcp", "smcp_stdio")}
    root = logging.getLogger()
    seeded_root = logging.StreamHandler(sys.stdout)
    root.addHandler(seeded_root)
    try:
        smcp_spec = importlib.util.spec_from_file_location("smcp", str(_repo_root / "smcp.py"))
        smcp_file = importlib.util.module_from_spec(smcp_spec)
        sys.modules["smcp"] = smcp_file
        smcp_spec.loader.exec_module(smcp_file)

        # Seed a stdout handler AND a stderr handler on smcp.logger so both
        # branches of the redirect loop execute.
        seeded_stdout = logging.StreamHandler(sys.stdout)
        seeded_stderr = logging.StreamHandler(sys.stderr)
        smcp_file.logger.addHandler(seeded_stdout)
        smcp_file.logger.addHandler(seeded_stderr)

        stdio_spec = importlib.util.spec_from_file_location("smcp_stdio", str(_repo_root / "smcp_stdio.py"))
        stdio = importlib.util.module_from_spec(stdio_spec)
        sys.modules["smcp_stdio"] = stdio
        stdio_spec.loader.exec_module(stdio)

        # The stdout handler must have been removed from smcp.logger.
        assert seeded_stdout not in smcp_file.logger.handlers
        # The stderr handler is kept (redirected/leveled), not removed.
        assert seeded_stderr in smcp_file.logger.handlers
        # Root's stdout handler must have been removed.
        assert seeded_root not in logging.getLogger().handlers
    finally:
        root.removeHandler(seeded_root)
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
