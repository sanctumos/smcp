"""
Tests for bundled demo_math and demo_text plugin CLIs (real subprocess + --describe).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Repo root: tests/unit -> smcp/
REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_MATH_CLI = REPO_ROOT / "plugins" / "demo_math" / "cli.py"
DEMO_TEXT_CLI = REPO_ROOT / "plugins" / "demo_text" / "cli.py"


def _run(cli: Path, argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(cli), *argv],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


@pytest.mark.unit
class TestDemoMathPlugin:
    def test_describe_valid_json_and_commands(self):
        proc = _run(DEMO_MATH_CLI, ["--describe"])
        assert proc.returncode == 0, proc.stderr
        spec = json.loads(proc.stdout)
        assert spec["plugin"]["name"] == "demo_math"
        assert "commands" in spec
        names = {c["name"] for c in spec["commands"]}
        assert names == {"calculate", "format_bytes", "coin_flip"}

    def test_calculate_add(self):
        proc = _run(
            DEMO_MATH_CLI,
            ["calculate", "--operation", "add", "--a", "2", "--b", "3"],
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["ok"] is True
        assert out["result"] == 5.0

    def test_calculate_divide_by_zero(self):
        proc = _run(
            DEMO_MATH_CLI,
            ["calculate", "--operation", "divide", "--a", "1", "--b", "0"],
        )
        assert proc.returncode == 1
        out = json.loads(proc.stdout)
        assert out["ok"] is False
        assert out["error"] == "division_by_zero"

    def test_format_bytes(self):
        proc = _run(DEMO_MATH_CLI, ["format_bytes", "--value", "2048"])
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["ok"] is True
        assert "KiB" in out["human"]

    def test_coin_flip_shape(self):
        proc = _run(DEMO_MATH_CLI, ["coin_flip"])
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["ok"] is True
        assert out["result"] in ("heads", "tails")


@pytest.mark.unit
class TestDemoTextPlugin:
    def test_describe_valid_json_and_commands(self):
        proc = _run(DEMO_TEXT_CLI, ["--describe"])
        assert proc.returncode == 0, proc.stderr
        spec = json.loads(proc.stdout)
        assert spec["plugin"]["name"] == "demo_text"
        names = {c["name"] for c in spec["commands"]}
        assert names == {"echo", "word_count", "slugify", "hash_preview"}

    def test_word_count(self):
        proc = _run(
            DEMO_TEXT_CLI,
            ["word_count", "--text", "one two three"],
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["ok"] is True
        assert out["words"] == 3

    def test_slugify(self):
        proc = _run(
            DEMO_TEXT_CLI,
            ["slugify", "--title", "Hello World!"],
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["ok"] is True
        assert out["slug"] == "hello-world"

    def test_echo_with_prefix(self):
        proc = _run(
            DEMO_TEXT_CLI,
            ["echo", "--message", "there", "--prefix", "hi"],
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["ok"] is True
        assert out["output"] == "hi: there"

    def test_hash_preview_deterministic(self):
        proc = _run(
            DEMO_TEXT_CLI,
            ["hash_preview", "--text", "same"],
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["ok"] is True
        assert len(out["sha256_preview"]) == 16


@pytest.mark.unit
class TestDescribeIntegrationWithSmcp:
    """get_plugin_describe against real bundled plugin files."""

    def test_get_plugin_describe_demo_math(self):
        sys.path.insert(0, str(REPO_ROOT))
        import importlib.util

        spec = importlib.util.spec_from_file_location("smcp_module", REPO_ROOT / "smcp.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        spec_json = mod.get_plugin_describe("demo_math", str(DEMO_MATH_CLI))
        assert spec_json is not None
        assert "commands" in spec_json
        assert any(c["name"] == "calculate" for c in spec_json["commands"])
