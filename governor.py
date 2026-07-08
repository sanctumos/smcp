"""
SMCP session attach registry (Phase 2b plane B).

Profiles (which tools are attached by default) are **configuration-driven**
(issue #45). The core ships only generic built-ins (`full`, and optionally
namespace-based `admin` when ``SMCP_ADMIN_PREFIX`` is set). Product-specific
tool lists live in external JSON loaded via ``SMCP_PROFILES``.

Issue #46: all mutable attach/catalog/profile state lives on a ``Governor``
instance so multiple server contexts can coexist in one process without
cross-talk. There is no process-global attach state.
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


def _builtin_profiles() -> Dict[str, Dict[str, Any]]:
    """Return generic built-in profiles (may include env-driven admin)."""
    profiles = dict(_BUILTIN_PROFILES)
    prefix = (os.getenv("SMCP_ADMIN_PREFIX") or "").strip()
    if prefix:
        profiles["admin"] = {"mode": "prefix", "prefix": prefix}
    return profiles


class Governor:
    """Per-session attach registry: catalog, profiles, and attached tools.

    Construct one instance per MCP server context. Instances do not share state.
    """

    def __init__(self) -> None:
        self._attached: Set[str] = set()
        self._catalog: Set[str] = set()
        self._bootstrapped = False
        self._profiles_loaded = False
        self._profile_defs: Dict[str, Dict[str, Any]] = {}
        self._intent_hints: List[Dict[str, Any]] = []
        self._default_profile = "full"
        self._active_profile: Optional[str] = None

    def _merge_profile_config(self, data: Dict[str, Any]) -> None:
        """Merge one parsed profile-config document into this instance."""
        if isinstance(data.get("default_profile"), str) and data["default_profile"].strip():
            self._default_profile = data["default_profile"].strip().lower()

        profiles = data.get("profiles")
        if isinstance(profiles, dict):
            for name, spec in profiles.items():
                if isinstance(name, str) and isinstance(spec, dict):
                    self._profile_defs[name.strip().lower()] = spec

        hints = data.get("intent_hints")
        if isinstance(hints, list):
            self._intent_hints.extend(h for h in hints if isinstance(h, dict))

    def _load_profile_file(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"failed to load SMCP profile config {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"SMCP profile config {path} must be a JSON object")
        self._merge_profile_config(data)

    def _ensure_profiles_loaded(self) -> None:
        if self._profiles_loaded:
            return

        self._profile_defs = _builtin_profiles()
        self._intent_hints = []

        cfg = (os.getenv("SMCP_PROFILES") or "").strip()
        if cfg:
            p = Path(cfg)
            if p.is_dir():
                files = sorted(p.glob("*.json"))
                if not files:
                    raise ValueError(f"SMCP_PROFILES directory {p} contains no *.json files")
                for fp in files:
                    self._load_profile_file(fp)
            elif p.is_file():
                self._load_profile_file(p)
            else:
                raise ValueError(f"SMCP_PROFILES path does not exist: {cfg}")

        self._profiles_loaded = True

    def profile_names(self) -> List[str]:
        self._ensure_profiles_loaded()
        return sorted(self._profile_defs.keys())

    def _resolve_profile_tools(self, profile: str) -> Set[str]:
        """Resolve a profile name to the tool names it attaches from the catalog."""
        self._ensure_profiles_loaded()
        spec = self._profile_defs.get(profile)
        if spec is None:
            raise ValueError(f"unknown profile: {profile}")

        mode = (spec.get("mode") or "all").strip().lower()

        if mode == "all":
            return set(self._catalog)

        if mode == "prefix":
            prefix = spec.get("prefix")
            if not isinstance(prefix, str) or not prefix:
                raise ValueError(f"profile {profile!r} with mode=prefix requires a non-empty 'prefix'")
            return {n for n in self._catalog if n.startswith(prefix)}

        if mode == "glob":
            pattern = spec.get("pattern")
            if not isinstance(pattern, str) or not pattern:
                raise ValueError(f"profile {profile!r} with mode=glob requires a 'pattern'")
            return {n for n in self._catalog if fnmatch.fnmatch(n, pattern)}

        if mode == "explicit":
            tools = spec.get("tools")
            if not isinstance(tools, list):
                raise ValueError(f"profile {profile!r} with mode=explicit requires a 'tools' array")
            want = {str(t) for t in tools}
            return want & self._catalog

        raise ValueError(f"profile {profile!r} has unsupported mode: {mode!r}")

    def _effective_profile(self) -> str:
        """Pick the attach profile from env, active, or default, falling back to ``full``."""
        self._ensure_profiles_loaded()
        env_profile = (os.getenv("SMCP_ATTACH_PROFILE") or "").strip().lower()
        for candidate in (env_profile, self._active_profile, self._default_profile, "full"):
            if candidate and candidate in self._profile_defs:
                return candidate
        return "full"

    def _bootstrap(self) -> None:
        if self._bootstrapped:
            return
        profile = self._effective_profile()
        if profile in self._profile_defs:
            self.attach_profile(profile)
        self._bootstrapped = True

    def set_catalog(self, tool_names: Iterable[str]) -> None:
        self._catalog = set(tool_names)
        # Keep attachments in sync whenever the catalog changes.
        profile = self._effective_profile()
        if profile in self._profile_defs:
            self.attach_profile(profile)

    def attach(self, tool_name: str) -> bool:
        if tool_name not in self._catalog and tool_name != GOVERNOR_TOOL_NAME:
            return False
        self._attached.add(tool_name)
        return True

    def detach(self, tool_name: str) -> bool:
        if tool_name == GOVERNOR_TOOL_NAME:
            return False
        if tool_name in self._attached:
            self._attached.remove(tool_name)
            return True
        return False

    def attach_profile(self, profile: str) -> Dict[str, Any]:
        profile = profile.strip().lower()
        self._attached.clear()
        self._attached.add(GOVERNOR_TOOL_NAME)
        self._attached.update(self._resolve_profile_tools(profile))
        self._active_profile = profile
        return {"profile": profile, "attached": sorted(self._attached)}

    def list_attached(self) -> List[str]:
        self._bootstrap()
        return sorted(self._attached)

    def list_available(self) -> List[str]:
        return sorted(self._catalog)

    def is_attached(self, tool_name: str) -> bool:
        self._bootstrap()
        return tool_name in self._attached or tool_name == GOVERNOR_TOOL_NAME

    def filter_tools(self, all_tools: List[Tool]) -> List[Tool]:
        if not self._catalog:
            self.set_catalog(t.name for t in all_tools if t.name != GOVERNOR_TOOL_NAME)
        self._bootstrap()
        out = [t for t in all_tools if self.is_attached(t.name)]
        if not any(t.name == GOVERNOR_TOOL_NAME for t in out):
            out.insert(0, self.governor_tool())
        return out

    def governor_tool(self) -> Tool:
        self._ensure_profiles_loaded()
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
                    "profile": {"type": "string", "enum": self.profile_names()},
                    "intent": {"type": "string"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        )

    def handle(self, arguments: dict) -> str:
        action = (arguments.get("action") or "").strip().lower().replace("_", "-")
        if action == "list-available":
            return json.dumps({"tools": self.list_available()}, indent=2)
        if action == "list-attached":
            return json.dumps({"tools": self.list_attached()}, indent=2)
        if action == "attach":
            names = arguments.get("tools") or (
                [arguments["tool"]] if arguments.get("tool") else []
            )
            ok = [n for n in names if self.attach(str(n))]
            return json.dumps({"attached": ok, "attached_set": self.list_attached()}, indent=2)
        if action == "detach":
            names = arguments.get("tools") or (
                [arguments["tool"]] if arguments.get("tool") else []
            )
            ok = [n for n in names if self.detach(str(n))]
            return json.dumps({"detached": ok, "attached_set": self.list_attached()}, indent=2)
        if action == "attach-profile":
            prof = arguments.get("profile") or self._default_profile
            return json.dumps(self.attach_profile(str(prof)), indent=2)
        if action == "help":
            self._ensure_profiles_loaded()
            intent = (arguments.get("intent") or "").strip().lower()
            hints = list(self._intent_hints)
            if intent:
                hints = [
                    h
                    for h in hints
                    if intent in str(h.get("intent", "")).lower()
                    or intent in str(h.get("tool", "")).lower()
                ]
            profiles_note = ", ".join(self.profile_names()) or "full"
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

    def gate_tool_call(self, tool_name: str) -> Optional[str]:
        self._bootstrap()
        if self.is_attached(tool_name):
            return None
        return json.dumps(
            {
                "error": "tool_not_attached",
                "tool": tool_name,
                "hint": (
                    f"Run {GOVERNOR_TOOL_NAME} action=attach tool={tool_name} "
                    "or action=attach-profile"
                ),
                "attached": self.list_attached(),
            },
            indent=2,
        )
