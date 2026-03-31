#!/usr/bin/env python3
"""
Broca SMCP plugin — wraps Broca core CLIs (queue, users, conversations, settings, btool, outbound).

Environment:
  BROCA_ROOT   — cwd for CLI (agent instance; contains sanctum.db). Default: getcwd().
  BROCA_SRC    — PYTHONPATH root containing `cli` package. Default: BROCA_ROOT.
  BROCA_PYTHON — Python with Broca deps. Default: sys.executable (set explicitly in prod).

Copyright (c) 2026 Sanctum OS — AGPL-3.0
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

PLUGIN_SPEC: dict[str, Any] = {
    "plugin": {
        "name": "broca",
        "version": "0.2.0",
        "description": "Administer a Broca instance via official CLIs (queue, users, conversations, settings, telegram ignore list, outbound send).",
    },
    "commands": [
        {
            "name": "queue_list",
            "description": "List all queue items (--json).",
            "parameters": [],
        },
        {
            "name": "queue_flush",
            "description": "Flush queue item(s). scope=all or scope=single with item_id.",
            "parameters": [
                {
                    "name": "scope",
                    "type": "string",
                    "description": "'all' or 'single'",
                    "required": True,
                },
                {
                    "name": "item_id",
                    "type": "number",
                    "description": "Queue row id when scope is single",
                    "required": False,
                },
            ],
        },
        {
            "name": "queue_delete",
            "description": "Delete queue item(s). scope=all or scope=single with item_id.",
            "parameters": [
                {
                    "name": "scope",
                    "type": "string",
                    "description": "'all' or 'single'",
                    "required": True,
                },
                {
                    "name": "item_id",
                    "type": "number",
                    "description": "Queue row id when scope is single",
                    "required": False,
                },
            ],
        },
        {
            "name": "user_list",
            "description": "List Letta users / platform profiles summary.",
            "parameters": [],
        },
        {
            "name": "user_get",
            "description": "Get one user by letta user id.",
            "parameters": [
                {
                    "name": "user_id",
                    "type": "number",
                    "description": "letta_users.id",
                    "required": True,
                },
            ],
        },
        {
            "name": "user_set_status",
            "description": "Set user active or inactive.",
            "parameters": [
                {
                    "name": "user_id",
                    "type": "number",
                    "description": "letta_users.id",
                    "required": True,
                },
                {
                    "name": "status",
                    "type": "string",
                    "description": "active or inactive",
                    "required": True,
                },
            ],
        },
        {
            "name": "conversation_list",
            "description": "List recent conversation rows from DB view.",
            "parameters": [],
        },
        {
            "name": "conversation_get",
            "description": "Get conversation history for a letta user + platform profile.",
            "parameters": [
                {
                    "name": "letta_user_id",
                    "type": "number",
                    "description": "letta_users.id",
                    "required": True,
                },
                {
                    "name": "platform_profile_id",
                    "type": "number",
                    "description": "platform_profiles.id",
                    "required": True,
                },
                {
                    "name": "limit",
                    "type": "number",
                    "description": "Max messages (default 10)",
                    "required": False,
                    "default": 10,
                },
            ],
        },
        {
            "name": "settings_get",
            "description": "Show settings.json values.",
            "parameters": [],
        },
        {
            "name": "settings_set_mode",
            "description": "Set message mode echo|listen|live.",
            "parameters": [
                {
                    "name": "mode",
                    "type": "string",
                    "description": "echo, listen, or live",
                    "required": True,
                },
            ],
        },
        {
            "name": "settings_set_debug",
            "description": "Enable or disable debug in settings.json.",
            "parameters": [
                {
                    "name": "state",
                    "type": "string",
                    "description": "enabled or disabled (SMCP omits false booleans, so use this string)",
                    "required": True,
                },
            ],
        },
        {
            "name": "settings_set_refresh",
            "description": "Set queue refresh interval seconds in settings.json.",
            "parameters": [
                {
                    "name": "seconds",
                    "type": "number",
                    "description": "Interval >= 1",
                    "required": True,
                },
            ],
        },
        {
            "name": "settings_set_retries",
            "description": "Set max retries in settings.json.",
            "parameters": [
                {
                    "name": "retries",
                    "type": "number",
                    "description": "Non-negative integer",
                    "required": True,
                },
            ],
        },
        {
            "name": "settings_reload",
            "description": "Touch settings.json to trigger Broca hot-reload.",
            "parameters": [],
        },
        {
            "name": "send_outbound",
            "description": "Send outbound message to a user on a platform (v1: telegram). Requires ENABLE_OUTBOUND_TOOL=true on the Broca instance.",
            "parameters": [
                {
                    "name": "letta_user_id",
                    "type": "number",
                    "description": "letta_users.id",
                    "required": True,
                },
                {
                    "name": "platform",
                    "type": "string",
                    "description": "Platform name, e.g. telegram",
                    "required": True,
                },
                {
                    "name": "message",
                    "type": "string",
                    "description": "Message body (markdown ok for telegram)",
                    "required": True,
                },
                {
                    "name": "dry_run",
                    "type": "string",
                    "description": "yes = validate only; no = insert audit row and send",
                    "required": False,
                    "default": "no",
                },
                {
                    "name": "idempotency_key",
                    "type": "string",
                    "description": "Optional correlation key (reserved for future dedup)",
                    "required": False,
                },
            ],
        },
        {
            "name": "telegram_ignore_list",
            "description": "List Telegram bots on broca ignore list (plain text; no --json in btool).",
            "parameters": [],
        },
        {
            "name": "telegram_ignore_add",
            "description": "Add bot username or id to telegram_ignore_list.json.",
            "parameters": [
                {
                    "name": "identifier",
                    "type": "string",
                    "description": "Username (with or without @) or numeric id",
                    "required": True,
                },
                {
                    "name": "bot_id",
                    "type": "string",
                    "description": "Optional Telegram numeric id",
                    "required": False,
                },
            ],
        },
        {
            "name": "telegram_ignore_remove",
            "description": "Remove bot from ignore list by username or id.",
            "parameters": [
                {
                    "name": "identifier",
                    "type": "string",
                    "description": "Username or id",
                    "required": True,
                },
            ],
        },
    ],
}


def _broca_env() -> tuple[str, str, str, dict[str, str]]:
    """Returns (python, root, src, env) for subprocess."""
    py = (os.environ.get("BROCA_PYTHON") or sys.executable).strip() or sys.executable
    root = (os.environ.get("BROCA_ROOT") or os.getcwd()).strip() or os.getcwd()
    src = (os.environ.get("BROCA_SRC") or root).strip() or root
    env = os.environ.copy()
    env["PYTHONPATH"] = src
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return py, root, src, env


def _run(
    module: str,
    argv: list[str],
    *,
    timeout: int = 300,
) -> dict[str, Any]:
    py, root, _src, env = _broca_env()
    cmd = [py, "-m", module, *argv]
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "error": f"Timeout after {timeout}s: {' '.join(cmd)}", "detail": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e), "command": cmd}

    out = {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "command": cmd,
        "cwd": root,
    }
    if proc.stdout.strip():
        try:
            out["json"] = json.loads(proc.stdout.strip())
        except json.JSONDecodeError:
            out["json"] = None
    return out


def _emit(payload: dict[str, Any], rc: int) -> None:
    print(json.dumps(payload, indent=2))
    sys.exit(rc)


def cmd_queue_list(_args: argparse.Namespace) -> None:
    r = _run("cli.qtool", ["--json", "list"])
    if r.get("ok") and r.get("json") is not None:
        _emit({"ok": True, "data": r["json"]}, 0)
    _emit(r, 1 if not r.get("ok") else 0)


def cmd_queue_flush(args: argparse.Namespace) -> None:
    if args.scope == "all":
        r = _run("cli.qtool", ["flush", "--all"])
    else:
        if args.item_id is None:
            _emit({"ok": False, "error": "item_id required when scope=single"}, 1)
        r = _run("cli.qtool", ["flush", "--id", str(int(args.item_id))])
    _emit({"ok": r.get("ok", False), "broca": r}, 0 if r.get("ok") else 1)


def cmd_queue_delete(args: argparse.Namespace) -> None:
    if args.scope == "all":
        r = _run("cli.qtool", ["delete", "--all"])
    else:
        if args.item_id is None:
            _emit({"ok": False, "error": "item_id required when scope=single"}, 1)
        r = _run("cli.qtool", ["delete", "--id", str(int(args.item_id))])
    _emit({"ok": r.get("ok", False), "broca": r}, 0 if r.get("ok") else 1)


def cmd_user_list(_args: argparse.Namespace) -> None:
    r = _run("cli.utool", ["--json", "list"])
    if r.get("ok") and r.get("json") is not None:
        _emit({"ok": True, "data": r["json"]}, 0)
    _emit(r, 1 if not r.get("ok") else 0)


def cmd_user_get(args: argparse.Namespace) -> None:
    r = _run("cli.utool", ["--json", "get", str(int(args.user_id))])
    if r.get("ok") and r.get("json") is not None:
        _emit({"ok": True, "data": r["json"]}, 0)
    _emit(r, 1 if not r.get("ok") else 0)


def cmd_user_set_status(args: argparse.Namespace) -> None:
    # utool update does not emit JSON; rely on return code and stdout.
    r = _run(
        "cli.utool",
        ["--json", "update", str(int(args.user_id)), args.status],
    )
    _emit({"ok": r.get("ok", False), "broca": r}, 0 if r.get("ok") else 1)


def cmd_conversation_list(_args: argparse.Namespace) -> None:
    r = _run("cli.ctool", ["--json", "list"])
    if r.get("ok") and r.get("json") is not None:
        _emit({"ok": True, "data": r["json"]}, 0)
    _emit(r, 1 if not r.get("ok") else 0)


def cmd_conversation_get(args: argparse.Namespace) -> None:
    lim = int(args.limit) if args.limit is not None else 10
    r = _run(
        "cli.ctool",
        [
            "--json",
            "get",
            str(int(args.letta_user_id)),
            str(int(args.platform_profile_id)),
            "--limit",
            str(lim),
        ],
    )
    if r.get("ok") and r.get("json") is not None:
        _emit({"ok": True, "data": r["json"]}, 0)
    _emit(r, 1 if not r.get("ok") else 0)


def cmd_settings_get(_args: argparse.Namespace) -> None:
    r = _run("cli.settings", ["--json", "get"])
    if r.get("ok") and r.get("json") is not None:
        _emit({"ok": True, "data": r["json"]}, 0)
    _emit(r, 1 if not r.get("ok") else 0)


def cmd_settings_set_mode(args: argparse.Namespace) -> None:
    r = _run("cli.settings", ["--json", "mode", args.mode])
    if r.get("ok") and r.get("json") is not None:
        _emit({"ok": True, "data": r["json"]}, 0)
    _emit({"ok": r.get("ok", False), "broca": r}, 0 if r.get("ok") else 1)


def cmd_settings_set_debug(args: argparse.Namespace) -> None:
    st = (args.state or "").strip().lower()
    if st in ("enabled", "enable", "on", "true", "1"):
        r = _run("cli.settings", ["--json", "debug", "--enable"])
    elif st in ("disabled", "disable", "off", "false", "0"):
        r = _run("cli.settings", ["--json", "debug", "--disable"])
    else:
        _emit(
            {
                "ok": False,
                "error": "state must be enabled or disabled (or common synonyms)",
            },
            1,
        )
        return
    if r.get("ok") and r.get("json") is not None:
        _emit({"ok": True, "data": r["json"]}, 0)
    _emit({"ok": r.get("ok", False), "broca": r}, 0 if r.get("ok") else 1)


def cmd_settings_set_refresh(args: argparse.Namespace) -> None:
    r = _run("cli.settings", ["--json", "refresh", str(int(args.seconds))])
    if r.get("ok") and r.get("json") is not None:
        _emit({"ok": True, "data": r["json"]}, 0)
    _emit({"ok": r.get("ok", False), "broca": r}, 0 if r.get("ok") else 1)


def cmd_settings_set_retries(args: argparse.Namespace) -> None:
    r = _run("cli.settings", ["--json", "retries", str(int(args.retries))])
    if r.get("ok") and r.get("json") is not None:
        _emit({"ok": True, "data": r["json"]}, 0)
    _emit({"ok": r.get("ok", False), "broca": r}, 0 if r.get("ok") else 1)


def cmd_settings_reload(_args: argparse.Namespace) -> None:
    r = _run("cli.settings", ["--json", "reload"])
    if r.get("ok") and r.get("json") is not None:
        _emit({"ok": True, "data": r["json"]}, 0)
    _emit({"ok": r.get("ok", False), "broca": r}, 0 if r.get("ok") else 1)


def cmd_send_outbound(args: argparse.Namespace) -> None:
    dry = (getattr(args, "dry_run", None) or "no").strip().lower()
    if dry not in ("yes", "no"):
        dry = "no"
    argv = [
        "send",
        "--letta-user-id",
        str(int(args.letta_user_id)),
        "--platform",
        str(args.platform),
        "--message",
        str(args.message),
        "--dry-run",
        dry,
    ]
    if getattr(args, "idempotency_key", None):
        argv.extend(["--idempotency-key", str(args.idempotency_key)])
    r = _run("cli.outbound", argv, timeout=120)
    payload = r.get("json") if isinstance(r.get("json"), dict) else {}
    if not payload and (r.get("stdout") or "").strip():
        try:
            payload = json.loads(r["stdout"].strip())
        except json.JSONDecodeError:
            payload = {}
    success = bool(r.get("ok")) and bool(payload.get("success"))
    _emit({"ok": success, "data": payload, "broca": r}, 0 if success else 1)


def cmd_telegram_ignore_list(_args: argparse.Namespace) -> None:
    r = _run("cli.btool", ["list"], timeout=60)
    _emit({"ok": r.get("ok", False), "stdout": r.get("stdout"), "stderr": r.get("stderr")}, 0 if r.get("ok") else 1)


def cmd_telegram_ignore_add(args: argparse.Namespace) -> None:
    cmd = ["add", args.identifier]
    if args.bot_id:
        cmd.extend(["--id", args.bot_id])
    r = _run("cli.btool", cmd, timeout=60)
    _emit({"ok": r.get("ok", False), "broca": r}, 0 if r.get("ok") else 1)


def cmd_telegram_ignore_remove(args: argparse.Namespace) -> None:
    r = _run("cli.btool", ["remove", args.identifier], timeout=60)
    _emit({"ok": r.get("ok", False), "broca": r}, 0 if r.get("ok") else 1)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--describe":
        print(json.dumps(PLUGIN_SPEC, indent=2))
        sys.exit(0)

    parser = argparse.ArgumentParser(description="Broca SMCP plugin CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("queue_list")

    p = sub.add_parser("queue_flush")
    p.add_argument("--scope", choices=["all", "single"], required=True)
    p.add_argument("--item-id", type=int, default=None)

    p = sub.add_parser("queue_delete")
    p.add_argument("--scope", choices=["all", "single"], required=True)
    p.add_argument("--item-id", type=int, default=None)

    sub.add_parser("user_list")

    p = sub.add_parser("user_get")
    p.add_argument("--user-id", type=int, required=True)

    p = sub.add_parser("user_set_status")
    p.add_argument("--user-id", type=int, required=True)
    p.add_argument("--status", choices=["active", "inactive"], required=True)

    sub.add_parser("conversation_list")

    p = sub.add_parser("conversation_get")
    p.add_argument("--letta-user-id", type=int, required=True)
    p.add_argument("--platform-profile-id", type=int, required=True)
    p.add_argument("--limit", type=int, default=10)

    sub.add_parser("settings_get")

    p = sub.add_parser("settings_set_mode")
    p.add_argument("--mode", choices=["echo", "listen", "live"], required=True)

    p = sub.add_parser("settings_set_debug")
    p.add_argument("--state", required=True, help="enabled or disabled")

    p = sub.add_parser("settings_set_refresh")
    p.add_argument("--seconds", type=int, required=True)

    p = sub.add_parser("settings_set_retries")
    p.add_argument("--retries", type=int, required=True)

    sub.add_parser("settings_reload")

    p = sub.add_parser("send_outbound")
    p.add_argument("--letta-user-id", type=int, required=True)
    p.add_argument("--platform", required=True)
    p.add_argument("--message", required=True)
    p.add_argument("--dry-run", choices=["yes", "no"], default="no")
    p.add_argument("--idempotency-key", default=None, dest="idempotency_key")

    sub.add_parser("telegram_ignore_list")

    p = sub.add_parser("telegram_ignore_add")
    p.add_argument("--identifier", required=True)
    p.add_argument("--bot-id", default=None)

    p = sub.add_parser("telegram_ignore_remove")
    p.add_argument("--identifier", required=True)

    p_map = {
        "queue_list": cmd_queue_list,
        "queue_flush": cmd_queue_flush,
        "queue_delete": cmd_queue_delete,
        "user_list": cmd_user_list,
        "user_get": cmd_user_get,
        "user_set_status": cmd_user_set_status,
        "conversation_list": cmd_conversation_list,
        "conversation_get": cmd_conversation_get,
        "settings_get": cmd_settings_get,
        "settings_set_mode": cmd_settings_set_mode,
        "settings_set_debug": cmd_settings_set_debug,
        "settings_set_refresh": cmd_settings_set_refresh,
        "settings_set_retries": cmd_settings_set_retries,
        "settings_reload": cmd_settings_reload,
        "send_outbound": cmd_send_outbound,
        "telegram_ignore_list": cmd_telegram_ignore_list,
        "telegram_ignore_add": cmd_telegram_ignore_add,
        "telegram_ignore_remove": cmd_telegram_ignore_remove,
    }

    args = parser.parse_args()
    func = p_map.get(args.command)
    if func is None:
        parser.error(f"unknown command: {args.command}")
    func(args)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
