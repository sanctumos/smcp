"""
SMCP session attach registry (Phase 2b plane B).

Profiles (which tools are attached by default) are **configuration-driven**
(issue #45). The core ships only generic built-ins (`full`, and optionally
namespace-based `admin` when ``SMCP_ADMIN_PREFIX`` is set). Product-specific
tool lists live in external JSON loaded via ``SMCP_PROFILES``.
"""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from mcp.types import Tool

GOVERNOR_TOOL_NAME = "sanctum__tools"

# Generic built-in profiles — no product-specific tool names in core.
_BUILTIN_PROFILES: Dict[str, Dict[str, Any]] = {
    "full": {"mode": "all"},
}

_attached: Set[str] = set()
_catalog: Set[str] = set()
_bootstrapped = False
_profiles_loaded = False
_profile_defs: Dict[str, Dict[str, Any]] = {}
_intent_hints: List[Dict[str, Any]] = []
_default_profile = "full"
_active_profile: Optional[str] = None


def reset_for_tests() -> None:
    """Clear attach state and profile cache (unit tests only)."""
    global _bootstrapped, _profiles_loaded, _active_profile
    _attached.clear()
    _catalog.clear()
    _bootstrapped = False
    _profiles_loaded = False
    _profile_defs.clear()
    _intent_hints.clear()
    _default_profile = "full"
    _active_profile = None


def _builtin_profiles() -> Dict[str, Dict[str, Any]]:
    """Return generic built-in profiles (may include env-driven admin)."""
    profiles = dict(_BUILTIN_PROFILES)
    prefix = (os.getenv("SMCP_ADMIN_PREFIX") or "").strip()
    if prefix:
        profiles["admin"] = {"mode": "prefix", "prefix": prefix}
    return profiles


def _merge_profile_config(data: Dict[str, Any]) -> None:
    """Merge one parsed profile-config document into the module cache."""
    global _default_profile, _intent_hints

    if isinstance(data.get("default_profile"), str) and data["default_profile"].strip():
        _default_profile = data["default_profile"].strip().lower()

    profiles = data.get("profiles")
    if isinstance(profiles, dict):
        for name, spec in profiles.items():
            if isinstance(name, str) and isinstance(spec, dict):
                _profile_defs[name.strip().lower()] = spec

    hints = data.get("intent_hints")
    if isinstance(hints, list):
        _intent_hints.extend(h for h in hints if isinstance(h, dict))


def _load_profile_file(path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"failed to load SMCP profile config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"SMCP profile config {path} must be a JSON object")
    _merge_profile_config(data)


def _ensure_profiles_loaded() -> None:
    global _profiles_loaded, _profile_defs, _intent_hints, _default_profile
    if _profiles_loaded:
        return

    _profile_defs = _builtin_profiles()
    _intent_hints = []

    cfg = (os.getenv("SMCP_PROFILES") or "").strip()
    if cfg:
        p = Path(cfg)
        if p.is_dir():
            files = sorted(p.glob("*.json"))
            if not files:
                raise ValueError(f"SMCP_PROFILES directory {p} contains no *.json files")
            for fp in files:
                _load_profile_file(fp)
        elif p.is_file():
            _load_profile_file(p)
        else:
            raise ValueError(f"SMCP_PROFILES path does not exist: {cfg}")

    _profiles_loaded = True


def profile_names() -> List[str]:
    _ensure_profiles_loaded()
    return sorted(_profile_defs.keys())


def _resolve_profile_tools(profile: str) -> Set[str]:
    """Resolve a profile name to the tool names it attaches from the catalog."""
    _ensure_profiles_loaded()
    spec = _profile_defs.get(profile)
    if spec is None:
        raise ValueError(f"unknown profile: {profile}")

    mode = (spec.get("mode") or "all").strip().lower()

    if mode == "all":
        return set(_catalog)

    if mode == "prefix":
        prefix = spec.get("prefix")
        if not isinstance(prefix, str) or not prefix:
            raise ValueError(f"profile {profile!r} with mode=prefix requires a non-empty 'prefix'")
        return {n for n in _catalog if n.startswith(prefix)}

    if mode == "glob":
        pattern = spec.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError(f"profile {profile!r} with mode=glob requires a 'pattern'")
        return {n for n in _catalog if fnmatch.fnmatch(n, pattern)}

    if mode == "explicit":
        tools = spec.get("tools")
        if not isinstance(tools, list):
            raise ValueError(f"profile {profile!r} with mode=explicit requires a 'tools' array")
        want = {str(t) for t in tools}
        return want & _catalog

    raise ValueError(f"profile {profile!r} has unsupported mode: {mode!r}")


def _bootstrap() -> None:
    global _bootstrapped
    if _bootstrapped:
        return
    profile = _effective_profile()
    if profile in _profile_defs:
        attach_profile(profile)
    _bootstrapped = True


def _effective_profile() -> str:
    """Pick the attach profile from env, active, or default, falling back to ``full``."""
    _ensure_profiles_loaded()
    env_profile = (os.getenv("SMCP_ATTACH_PROFILE") or "").strip().lower()
    for candidate in (env_profile, _active_profile, _default_profile, "full"):
        if candidate and candidate in _profile_defs:
            return candidate
    return "full"


def set_catalog(tool_names: Iterable[str]) -> None:
    global _catalog, _active_profile
    _catalog = set(tool_names)
    # Keep attachments in sync whenever the catalog changes (register_plugin_tools
    # calls this after discovery). Without this, an early bootstrap on an empty
    # catalog can leave _bootstrapped=True with nothing attached except the
    # governor tool once real tools arrive.
    profile = _effective_profile()
    if profile in _profile_defs:
        attach_profile(profile)


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
    global _active_profile
    profile = profile.strip().lower()
    _attached.clear()
    _attached.add(GOVERNOR_TOOL_NAME)
    _attached.update(_resolve_profile_tools(profile))
    _active_profile = profile
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
    if not _catalog:
        set_catalog(t.name for t in all_tools if t.name != GOVERNOR_TOOL_NAME)
    _bootstrap()
    out = [t for t in all_tools if is_attached(t.name)]
    if not any(t.name == GOVERNOR_TOOL_NAME for t in out):
        out.insert(0, governor_tool())
    return out


def governor_tool() -> Tool:
    _ensure_profiles_loaded()
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
                "profile": {"type": "string", "enum": profile_names()},
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
        prof = arguments.get("profile") or _default_profile
        return json.dumps(attach_profile(str(prof)), indent=2)
    if action == "help":
        _ensure_profiles_loaded()
        intent = (arguments.get("intent") or "").strip().lower()
        hints = list(_intent_hints)
        if intent:
            hints = [
                h
                for h in hints
                if intent in str(h.get("intent", "")).lower()
                or intent in str(h.get("tool", "")).lower()
            ]
        profiles_note = ", ".join(profile_names()) or "full"
        return json.dumps(
            {
                "matches": hints,
                "note": (
                    "Detached tools return attach hint on call. "
                    f"Use attach-profile with one of: {profiles_note}."
                ),
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
