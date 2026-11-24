"""
E2E parity: demo plugins + sanctum__tools behave identically over
classic SSE and Streamable HTTP (/mcp).

Does not modify any plugin, the describe contract, or governor.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

_REPO = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        return s.getsockname()[1]


async def _wait_ready(base: str, timeout: float = 20.0) -> bool:
    start = time.time()
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.time() - start < timeout:
            try:
                # POST /sse is the Letta shim — returns 400 immediately (do not GET /sse;
                # that opens a long-lived stream and hangs the readiness probe).
                r = await client.post(f"{base}/sse", content=b"")
                if r.status_code in (400, 401, 405):
                    return True
            except (httpx.HTTPError, httpx.TimeoutException):
                pass
            await asyncio.sleep(0.25)
    return False


@pytest.fixture(scope="module")
async def parity_server():
    """One live SMCP process with bundled demo plugins; auth open for local e2e."""
    port = _free_port()
    env = os.environ.copy()
    env["MCP_AUTH_DISABLED"] = "1"
    # Discover plugins from the repo tree (cwd)
    cmd = [
        sys.executable,
        str(_REPO / "smcp.py"),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(_REPO),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        if proc.poll() is not None:
            out, err = proc.communicate()
            raise RuntimeError(f"parity server failed to start: {err or out}")
        ready = await _wait_ready(base)
        if not ready:
            proc.terminate()
            out, err = proc.communicate(timeout=5)
            raise RuntimeError(f"parity server not ready: {err or out}")
        yield {"base": base, "port": port, "proc": proc}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@contextlib.asynccontextmanager
async def _session_over_streamable(base: str):
    url = f"{base}/mcp"
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@contextlib.asynccontextmanager
async def _session_over_sse(base: str):
    url = f"{base}/sse"
    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _tool_catalog(tools_result):
    """name -> (description, inputSchema) for equality checks."""
    out = {}
    for t in tools_result.tools:
        schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None)
        if hasattr(schema, "model_dump"):
            schema = schema.model_dump(by_alias=True, exclude_none=True)
        out[t.name] = {
            "description": t.description,
            "inputSchema": schema,
        }
    return out


def _result_text(call_result) -> str:
    if not call_result.content:
        return ""
    first = call_result.content[0]
    return getattr(first, "text", str(first))


@pytest.mark.e2e
class TestStreamablePluginParity:
    async def test_harness_both_transports_initialize(self, parity_server):
        base = parity_server["base"]
        async with _session_over_streamable(base) as session:
            tools = await session.list_tools()
            assert any(t.name.startswith("demo_math__") for t in tools.tools)
        async with _session_over_sse(base) as session:
            tools = await session.list_tools()
            assert any(t.name.startswith("demo_math__") for t in tools.tools)

    async def test_tools_list_parity(self, parity_server):
        base = parity_server["base"]
        async with _session_over_streamable(base) as s_http:
            http_catalog = _tool_catalog(await s_http.list_tools())
        async with _session_over_sse(base) as s_sse:
            sse_catalog = _tool_catalog(await s_sse.list_tools())
        assert sorted(http_catalog.keys()) == sorted(sse_catalog.keys())
        for name in http_catalog:
            assert http_catalog[name]["inputSchema"] == sse_catalog[name]["inputSchema"]
            assert http_catalog[name]["description"] == sse_catalog[name]["description"]

    async def test_tools_call_demo_parity(self, parity_server):
        base = parity_server["base"]
        calls = [
            ("demo_text__echo", {"message": "parity-check"}),
            ("demo_math__format_bytes", {"value": 1024}),
        ]
        http_results = {}
        sse_results = {}
        async with _session_over_streamable(base) as s_http:
            for name, args in calls:
                r = await s_http.call_tool(name, args)
                http_results[name] = (r.is_error, _result_text(r))
        async with _session_over_sse(base) as s_sse:
            for name, args in calls:
                r = await s_sse.call_tool(name, args)
                sse_results[name] = (r.is_error, _result_text(r))
        assert http_results == sse_results
        for name, (is_err, _text) in http_results.items():
            assert is_err is False, name

    async def test_governor_parity(self, parity_server):
        base = parity_server["base"]
        async with _session_over_streamable(base) as s_http:
            r_http = await s_http.call_tool("sanctum__tools", {"action": "list-attached"})
            http_text = _result_text(r_http)
            assert r_http.is_error is False
        async with _session_over_sse(base) as s_sse:
            r_sse = await s_sse.call_tool("sanctum__tools", {"action": "list-attached"})
            sse_text = _result_text(r_sse)
            assert r_sse.is_error is False
        assert http_text == sse_text
        assert "demo_math__" in http_text or "demo_text__" in http_text

    async def test_unknown_tool_error_parity(self, parity_server):
        base = parity_server["base"]
        missing = "no_such_plugin__no_such_tool"
        async with _session_over_streamable(base) as s_http:
            r_http = await s_http.call_tool(missing, {})
            http_text = _result_text(r_http)
            http_err = r_http.is_error
        async with _session_over_sse(base) as s_sse:
            r_sse = await s_sse.call_tool(missing, {})
            sse_text = _result_text(r_sse)
            sse_err = r_sse.is_error
        # Governor returns a tool_not_attached JSON body (is_error may be False);
        # both transports must match exactly.
        assert http_err == sse_err
        assert http_text == sse_text
        assert "tool_not_attached" in http_text or "not found" in http_text.lower()
        assert missing.split("__")[0] in http_text or missing in http_text

    def test_execute_plugin_tool_has_no_transport_branch(self):
        """Transport must not leak into plugin spawn."""
        sys.path.insert(0, str(_REPO))
        import smcp as smcp_mod

        src = inspect.getsource(smcp_mod.execute_plugin_tool)
        forbidden = ("streamable", "/mcp", "sse_transport", "STREAMABLE_HTTP")
        hits = [tok for tok in forbidden if tok.lower() in src.lower()]
        assert hits == [], f"execute_plugin_tool references transport tokens: {hits}"
