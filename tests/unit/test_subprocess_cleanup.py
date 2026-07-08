"""
Subprocess lifecycle cleanup on cancel/disconnect (issue #18, sanctum #40).

Covers _terminate_process (SIGTERM -> SIGKILL escalation and no-op paths) and
verifies execute_plugin_tool terminates its child and re-raises when the awaiting
task is cancelled mid-run.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import asyncio
import sys
import importlib.util
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

_here = Path(__file__).resolve()
_repo_root = _here.parent.parent.parent
sys.path.insert(0, str(_repo_root))
_spec = importlib.util.spec_from_file_location("smcp_module", str(_repo_root / "smcp.py"))
smcp_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = smcp_module
_spec.loader.exec_module(smcp_module)


class _FakeProc:
    """Minimal asyncio subprocess stand-in for lifecycle tests."""

    def __init__(self, returncode=None, wait_hangs=False, terminate_exc=None,
                 wait_exc=None, kill_exc=None):
        self.returncode = returncode
        self._wait_hangs = wait_hangs
        self._terminate_exc = terminate_exc
        self._wait_exc = wait_exc
        self._kill_exc = kill_exc
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True
        if self._terminate_exc is not None:
            raise self._terminate_exc
        if not self._wait_hangs:
            self.returncode = -15

    def kill(self):
        self.killed = True
        if self._kill_exc is not None:
            raise self._kill_exc
        self.returncode = -9

    async def wait(self):
        if self._wait_exc is not None:
            raise self._wait_exc
        # Hang until killed when simulating a stubborn process.
        while self._wait_hangs and not self.killed:
            await asyncio.sleep(0.01)
        return self.returncode


@pytest.mark.unit
class TestTerminateProcess:
    async def test_none_is_noop(self):
        await smcp_module._terminate_process(None)  # must not raise

    async def test_already_exited_is_noop(self):
        proc = _FakeProc(returncode=0)
        await smcp_module._terminate_process(proc)
        assert proc.terminated is False and proc.killed is False

    async def test_graceful_terminate_no_kill(self):
        proc = _FakeProc(returncode=None, wait_hangs=False)
        await smcp_module._terminate_process(proc, grace=0.5)
        assert proc.terminated is True
        assert proc.killed is False

    async def test_escalates_to_kill_after_grace(self):
        proc = _FakeProc(returncode=None, wait_hangs=True)
        await smcp_module._terminate_process(proc, grace=0.05)
        assert proc.terminated is True
        assert proc.killed is True

    async def test_process_lookup_error_returns(self):
        proc = _FakeProc(returncode=None, terminate_exc=ProcessLookupError())
        await smcp_module._terminate_process(proc, grace=0.05)
        assert proc.terminated is True
        assert proc.killed is False

    async def test_generic_terminate_error_then_waits(self):
        # terminate raising a non-lookup error is swallowed; wait still runs.
        proc = _FakeProc(returncode=None, terminate_exc=ValueError("boom"))
        # wait returns None immediately (returncode stays None but not hanging)
        await smcp_module._terminate_process(proc, grace=0.05)
        assert proc.terminated is True

    async def test_wait_error_returns_without_kill(self):
        # process.wait() raising a non-timeout error is swallowed (no kill).
        proc = _FakeProc(returncode=None, wait_exc=RuntimeError("gone"))
        await smcp_module._terminate_process(proc, grace=0.05)
        assert proc.terminated is True
        assert proc.killed is False

    async def test_kill_error_is_swallowed(self):
        # escalation reached, but kill() raising is swallowed (no orphan crash).
        proc = _FakeProc(returncode=None, wait_hangs=True, kill_exc=OSError("nope"))
        await smcp_module._terminate_process(proc, grace=0.05)
        assert proc.terminated is True
        assert proc.killed is True


@pytest.mark.unit
class TestExecuteToolCancellation:
    async def test_cancel_terminates_subprocess_and_reraises(self):
        # A child whose output reads hang forever, so the tool is still awaiting
        # when we cancel it.
        class _HangStream:
            async def read(self, n=-1):
                await asyncio.sleep(3600)
                return b""

        proc = _FakeProc(returncode=None)
        proc.stdout = _HangStream()
        proc.stderr = _HangStream()

        registry = {"toy": {"path": "/x/cli.py", "commands": {}}}
        with patch.object(smcp_module, "plugin_registry", registry), \
             patch.object(smcp_module.asyncio, "create_subprocess_exec",
                          new=AsyncMock(return_value=proc)):
            task = asyncio.create_task(
                smcp_module.execute_plugin_tool("toy__echo", {"name": "x"})
            )
            # Let it spawn and start (hanging) reads.
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert proc.terminated is True or proc.killed is True
