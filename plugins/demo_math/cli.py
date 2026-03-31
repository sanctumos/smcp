#!/usr/bin/env python3
"""
demo_math — small working examples for SMCP (structured tools, no external services).

Copyright (c) 2026 Sanctum OS — AGPL-3.0
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from typing import Any

PLUGIN_SPEC: dict[str, Any] = {
    "plugin": {
        "name": "demo_math",
        "version": "1.0.0",
        "description": "Demo: arithmetic, formatting, and a random flip — shows typed MCP tools without APIs.",
    },
    "commands": [
        {
            "name": "calculate",
            "description": "Add, subtract, multiply, or divide two numbers.",
            "parameters": [
                {
                    "name": "operation",
                    "type": "string",
                    "description": "One of: add, subtract, multiply, divide",
                    "required": True,
                },
                {
                    "name": "a",
                    "type": "number",
                    "description": "First operand",
                    "required": True,
                },
                {
                    "name": "b",
                    "type": "number",
                    "description": "Second operand",
                    "required": True,
                },
            ],
        },
        {
            "name": "format_bytes",
            "description": "Turn a byte count into a human-readable string (base-1024).",
            "parameters": [
                {
                    "name": "value",
                    "type": "number",
                    "description": "Number of bytes (non-negative)",
                    "required": True,
                },
            ],
        },
        {
            "name": "coin_flip",
            "description": "Return heads or tails (useful smoke test that tools return fresh data).",
            "parameters": [],
        },
    ],
}


def _emit(obj: dict[str, Any], rc: int = 0) -> None:
    print(json.dumps(obj, indent=2))
    sys.exit(rc)


def cmd_calculate(args: argparse.Namespace) -> None:
    op = args.operation.lower()
    a, b = float(args.a), float(args.b)
    if op == "add":
        r = a + b
    elif op == "subtract":
        r = a - b
    elif op == "multiply":
        r = a * b
    elif op == "divide":
        if b == 0:
            _emit({"ok": False, "error": "division_by_zero"}, 1)
        r = a / b
    else:
        _emit(
            {
                "ok": False,
                "error": "invalid_operation",
                "hint": "use add, subtract, multiply, or divide",
            },
            1,
        )
    _emit({"ok": True, "operation": op, "a": a, "b": b, "result": r}, 0)


def cmd_format_bytes(args: argparse.Namespace) -> None:
    n = float(args.value)
    if n < 0:
        _emit({"ok": False, "error": "value must be non-negative"}, 1)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    v = n
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    label = f"{v:.2f} {units[i]}" if i > 0 else f"{int(n)} B"
    _emit({"ok": True, "bytes": int(n), "human": label}, 0)


def cmd_coin_flip(_args: argparse.Namespace) -> None:
    side = random.choice(["heads", "tails"])
    _emit({"ok": True, "result": side}, 0)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--describe":
        print(json.dumps(PLUGIN_SPEC, indent=2))
        sys.exit(0)

    parser = argparse.ArgumentParser(description="SMCP demo_math plugin")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("calculate")
    p.add_argument("--operation", required=True)
    p.add_argument("--a", type=float, required=True)
    p.add_argument("--b", type=float, required=True)

    p = sub.add_parser("format_bytes")
    p.add_argument("--value", type=float, required=True)

    sub.add_parser("coin_flip")

    m = {
        "calculate": cmd_calculate,
        "format_bytes": cmd_format_bytes,
        "coin_flip": cmd_coin_flip,
    }
    args = parser.parse_args()
    m[args.command](args)


if __name__ == "__main__":
    main()
