"""
Unit tests for smcp_stdio.py (the STDIO transport entry point), including
the graceful-shutdown and Windows stdout-flush ExceptionGroup handling.

Since #50 removed the repo-root ``__init__.py``, the directory is no longer an
importable package, so ``import smcp`` resolves unambiguously to ``smcp.py``
and no importlib file-loading workaround is needed here.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import sys
import contextlib
import importlib
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

import smcp  # noqa: F401 - resolves to smcp.py; imported for clarity/isolation
import smcp_stdio


@pytest.fixture
def stdio_mod():
    """The STDIO entry module (plain import; #50 removed the package collision)."""
    return smcp_stdio


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
            await stdio_mod.async_main()
        srv.run.assert_awaited_once()

    async def test_init_failure_exits_1(self, stdio_mod):
        with _patched(stdio_mod, create_side_effect=RuntimeError("boom")):
            with pytest.raises(SystemExit) as ei:
                await stdio_mod.async_main()
        assert ei.value.code == 1

    async def test_keyboard_interrupt_is_graceful(self, stdio_mod):
        with _patched(stdio_mod, run_side_effect=KeyboardInterrupt()):
            await stdio_mod.async_main()  # must not raise

    async def test_generic_exception_exits_1(self, stdio_mod):
        with _patched(stdio_mod, run_side_effect=ValueError("nope")):
            with pytest.raises(SystemExit) as ei:
                await stdio_mod.async_main()
        assert ei.value.code == 1

    async def test_exceptiongroup_non_win32_reraises(self, stdio_mod):
        eg = ExceptionGroup("grp", [ValueError("x")])
        with _patched(stdio_mod, run_side_effect=eg), patch.object(sys, "platform", "linux"):
            with pytest.raises(SystemExit) as ei:
                await stdio_mod.async_main()
        assert ei.value.code == 1

    async def test_exceptiongroup_win32_flush_is_graceful(self, stdio_mod):
        eg = ExceptionGroup("grp", [OSError(22, "flush")])
        with _patched(stdio_mod, run_side_effect=eg), patch.object(sys, "platform", "win32"):
            await stdio_mod.async_main()  # all flush errors -> non-fatal

    async def test_base_exceptiongroup_win32_partial_reraises(self, stdio_mod):
        beg = BaseExceptionGroup("grp", [KeyboardInterrupt()])
        with _patched(stdio_mod, run_side_effect=beg), patch.object(sys, "platform", "win32"):
            with pytest.raises(BaseException):
                await stdio_mod.async_main()

    async def test_base_exceptiongroup_win32_flush_is_graceful(self, stdio_mod):
        beg = BaseExceptionGroup("grp", [OSError(22, "flush")])
        with _patched(stdio_mod, run_side_effect=beg), patch.object(sys, "platform", "win32"):
            await stdio_mod.async_main()

    def test_sync_main_wraps_async(self, stdio_mod):
        """The console-script entry runs the async main via asyncio.run (#50)."""
        with patch.object(stdio_mod, "async_main", AsyncMock(return_value=None)) as am:
            stdio_mod.main()
        am.assert_awaited_once()


@pytest.mark.unit
def test_import_time_stdout_handler_cleanup():
    """
    smcp_stdio, at import, must strip/redirect any stdout-bound StreamHandlers
    on both the root logger and smcp.logger so JSON-RPC stdout stays clean.
    We seed stdout handlers first, then reload smcp_stdio to re-run its
    import-time cleanup and assert the effect.
    """
    import logging

    root = logging.getLogger()
    seeded_root = logging.StreamHandler(sys.stdout)
    root.addHandler(seeded_root)

    # Seed a stdout handler AND a stderr handler on smcp.logger so both
    # branches of the redirect loop execute.
    seeded_stdout = logging.StreamHandler(sys.stdout)
    seeded_stderr = logging.StreamHandler(sys.stderr)
    smcp.logger.addHandler(seeded_stdout)
    smcp.logger.addHandler(seeded_stderr)
    try:
        importlib.reload(smcp_stdio)  # re-runs the import-time handler cleanup

        # The stdout handler must have been removed from smcp.logger.
        assert seeded_stdout not in smcp.logger.handlers
        # The stderr handler is kept (redirected/leveled), not removed.
        assert seeded_stderr in smcp.logger.handlers
        # Root's stdout handler must have been removed.
        assert seeded_root not in logging.getLogger().handlers
    finally:
        root.removeHandler(seeded_root)
        smcp.logger.removeHandler(seeded_stdout)
        smcp.logger.removeHandler(seeded_stderr)
