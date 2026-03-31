#!/usr/bin/env python3
"""
demo_text — small working string utilities for SMCP (schemas + real output).

Copyright (c) 2026 Sanctum OS — AGPL-3.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import Any

PLUGIN_SPEC: dict[str, Any] = {
    "plugin": {
        "name": "demo_text",
        "version": "1.0.0",
        "description": "Demo: echo, counting, slug, short hash — shows string tools agents can compose.",
    },
    "commands": [
        {
            "name": "echo",
            "description": "Return a message with optional prefix (round-trip structured I/O).",
            "parameters": [
                {
                    "name": "message",
                    "type": "string",
                    "description": "Body text",
                    "required": True,
                },
                {
                    "name": "prefix",
                    "type": "string",
                    "description": "Optional label before the message",
                    "required": False,
                    "default": "",
                },
            ],
        },
        {
            "name": "word_count",
            "description": "Count whitespace-separated words in text.",
            "parameters": [
                {
                    "name": "text",
                    "type": "string",
                    "description": "Input text",
                    "required": True,
                },
            ],
        },
        {
            "name": "slugify",
            "description": "Lowercase slug from a title (alphanumeric and hyphens only).",
            "parameters": [
                {
                    "name": "title",
                    "type": "string",
                    "description": "Arbitrary phrase",
                    "required": True,
                },
            ],
        },
        {
            "name": "hash_preview",
            "description": "SHA-256 hex digest, first 16 chars only (not a security API).",
            "parameters": [
                {
                    "name": "text",
                    "type": "string",
                    "description": "Input to hash",
                    "required": True,
                },
            ],
        },
    ],
}


def _emit(obj: dict[str, Any], rc: int = 0) -> None:
    print(json.dumps(obj, indent=2))
    sys.exit(rc)


def cmd_echo(args: argparse.Namespace) -> None:
    prefix = (args.prefix or "").strip()
    body = args.message
    out = f"{prefix}: {body}" if prefix else body
    _emit({"ok": True, "output": out}, 0)


def cmd_word_count(args: argparse.Namespace) -> None:
    words = [w for w in re.split(r"\s+", args.text.strip()) if w]
    _emit({"ok": True, "words": len(words), "characters": len(args.text)}, 0)


def cmd_slugify(args: argparse.Namespace) -> None:
    s = args.title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    _emit({"ok": True, "slug": s or "untitled"}, 0)


def cmd_hash_preview(args: argparse.Namespace) -> None:
    h = hashlib.sha256(args.text.encode("utf-8")).hexdigest()
    _emit({"ok": True, "sha256_preview": h[:16], "algorithm": "sha256"}, 0)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--describe":
        print(json.dumps(PLUGIN_SPEC, indent=2))
        sys.exit(0)

    parser = argparse.ArgumentParser(description="SMCP demo_text plugin")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("echo")
    p.add_argument("--message", required=True)
    p.add_argument("--prefix", default="")

    p = sub.add_parser("word_count")
    p.add_argument("--text", required=True)

    p = sub.add_parser("slugify")
    p.add_argument("--title", required=True)

    p = sub.add_parser("hash_preview")
    p.add_argument("--text", required=True)

    m = {
        "echo": cmd_echo,
        "word_count": cmd_word_count,
        "slugify": cmd_slugify,
        "hash_preview": cmd_hash_preview,
    }
    args = parser.parse_args()
    m[args.command](args)


if __name__ == "__main__":
    main()
