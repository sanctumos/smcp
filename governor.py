"""
SMCP session attach registry (Phase 2b plane B).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional, Set

from mcp.types import Tool

GOVERNOR_TOOL_NAME = "sanctum__tools"

# tasks plugin chatter/admin command suffixes (tasks__ prefix added at wire)
_TASKS_PROFILES: Dict[str, Set[str]] = {
    "chatter": {
        "tasks__" + s
        for s in (
            "create-task",
            "update-task",
            "get-task",
            "search-tasks",
            "list-tasks",
            "create-comment",
            "list-comments",
            "get-document",
            "list-documents",
            "create-document",
            "update-document",
            "create-document-comment",
            "list-document-comments",
            "list-directory-projects",
            "list-todo-lists",
        )
    },
    "admin": set(),  # filled at runtime = all tasks__* discovered
    "full": set(),
}

_attached: Set[str] = set()
_catalog: Set[str] = set()
_bootstrapped = False


def reset_for_tests() -> None:
    """Clear attach state (unit tests only)."""
    global _bootstrapped
    _attached.clear()
    _catalog.clear()
    _bootstrapped = False
    _TASKS_PROFILES["admin"] = set()


def _bootstrap() -> None:
    global _bootstrapped
    if _bootstrapped:
        return
    profile = (os.getenv("SMCP_ATTACH_PROFILE") or "full").strip().lower()
    if profile in ("chatter", "admin", "full"):
        attach_profile(profile)
    _bootstrapped = True


def set_catalog(tool_names: Iterable[str]) -> None:
    global _catalog
    _catalog = set(tool_names)
    admin = {n for n in _catalog if n.startswith("tasks__")}
    _TASKS_PROFILES["admin"] = admin
    if (os.getenv("SMCP_ATTACH_PROFILE") or "").strip().lower() == "admin":
        _attached.clear()
        _attached.update(admin)
        _attached.add(GOVERNOR_TOOL_NAME)


def attach(tool_name: str) -> bool:
    if tool_name not in _catalog and tool_name != GOVERNOR_TOOL_NAME:
        return False
    _attached.add(tool_name)
    return True


def detach(tool_name: str) -> bool:
    if tool_name == GOVERNOR_TOOL_NAME:
        return False
    if tool_name in _attached:
        _attached.remove(tool_name)
        return True
    return False


def attach_profile(profile: str) -> Dict[str, Any]:
    profile = profile.strip().lower()
    _attached.clear()
    _attached.add(GOVERNOR_TOOL_NAME)
    if profile == "full":
        _attached.update(_catalog)
    elif profile == "admin":
        _attached.update(_TASKS_PROFILES.get("admin") or {n for n in _catalog if n.startswith("tasks__")})
    elif profile == "chatter":
        _attached.update(_TASKS_PROFILES["chatter"] & _catalog)
    else:
        raise ValueError(f"unknown profile: {profile}")
    return {"profile": profile, "attached": sorted(_attached)}


def list_attached() -> List[str]:
    _bootstrap()
    return sorted(_attached)


def list_available() -> List[str]:
    return sorted(_catalog)


def is_attached(tool_name: str) -> bool:
    _bootstrap()
    return tool_name in _attached or tool_name == GOVERNOR_TOOL_NAME


def filter_tools(all_tools: List[Tool]) -> List[Tool]:
    _bootstrap()
    if not _catalog:
        set_catalog(t.name for t in all_tools if t.name != GOVERNOR_TOOL_NAME)
    out = [t for t in all_tools if is_attached(t.name)]
    if not any(t.name == GOVERNOR_TOOL_NAME for t in out):
        out.insert(0, governor_tool())
    return out


def governor_tool() -> Tool:
    return Tool(
        name=GOVERNOR_TOOL_NAME,
        description="Sanctum SMCP governor: help, list/attach/detach tools, apply profiles.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "help",
                        "list-available",
                        "list-attached",
                        "attach",
                        "detach",
                        "attach-profile",
                    ],
                },
                "tool": {"type": "string"},
                "tools": {"type": "array", "items": {"type": "string"}},
                "profile": {"type": "string", "enum": ["chatter", "admin", "full"]},
                "intent": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    )


def handle_governor(arguments: dict) -> str:
    action = (arguments.get("action") or "").strip().lower().replace("_", "-")
    if action == "list-available":
        return json.dumps({"tools": list_available()}, indent=2)
    if action == "list-attached":
        return json.dumps({"tools": list_attached()}, indent=2)
    if action == "attach":
        names = arguments.get("tools") or ([arguments["tool"]] if arguments.get("tool") else [])
        ok = [n for n in names if attach(str(n))]
        return json.dumps({"attached": ok, "attached_set": list_attached()}, indent=2)
    if action == "detach":
        names = arguments.get("tools") or ([arguments["tool"]] if arguments.get("tool") else [])
        ok = [n for n in names if detach(str(n))]
        return json.dumps({"detached": ok, "attached_set": list_attached()}, indent=2)
    if action == "attach-profile":
        prof = arguments.get("profile") or "chatter"
        return json.dumps(attach_profile(str(prof)), indent=2)
    if action == "help":
        intent = (arguments.get("intent") or "").strip().lower()
        hints = [
            {"intent": "create task", "tool": "tasks__create-task", "needs": "list-id"},
            {"intent": "save document", "tool": "tasks__create-document", "needs": "project-id"},
            {"intent": "list project docs", "tool": "tasks__list-documents", "needs": "project-id"},
        ]
        if intent:
            hints = [h for h in hints if intent in h["intent"] or intent in h["tool"]]
        return json.dumps(
            {
                "matches": hints,
                "note": "Detached tools return attach hint on call. Use attach-profile chatter|admin|full.",
            },
            indent=2,
        )
    return json.dumps({"error": f"unknown action: {action}"}, indent=2)


def gate_tool_call(tool_name: str) -> Optional[str]:
    _bootstrap()
    if is_attached(tool_name):
        return None
    return json.dumps(
        {
            "error": "tool_not_attached",
            "tool": tool_name,
            "hint": f"Run {GOVERNOR_TOOL_NAME} action=attach tool={tool_name} or action=attach-profile",
            "attached": list_attached(),
        },
        indent=2,
    )
