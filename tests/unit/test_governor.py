"""
Unit tests for the SMCP session attach governor (governor.py).

Covers the full public surface: catalog/profile management, attach/detach
guards, tool filtering, the sanctum__tools handler actions, and call gating.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import json
import os
from pathlib import Path

import pytest

import governor
from mcp.types import Tool

_PROFILES_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "governor_profiles_sanctum.json"


@pytest.fixture(autouse=True)
def _sanctum_profile_config(monkeypatch):
    """Reproduce the legacy tasks/partner deployment via external config (#45)."""
    monkeypatch.setenv("SMCP_PROFILES", str(_PROFILES_FIXTURE))
    governor.reset_for_tests()


def _sample_tools():
    return [
        Tool(name="tasks__create-task", description="create", inputSchema={"type": "object"}),
        Tool(name="tasks__list-users", description="admin", inputSchema={"type": "object"}),
        Tool(name="tasks__get-document", description="doc", inputSchema={"type": "object"}),
        Tool(name="kitchen_pos_partner__menu", description="menu", inputSchema={"type": "object"}),
    ]


# governor's process-global state is reset before/after every test by the
# autouse _reset_governor_state fixture in tests/conftest.py.


@pytest.mark.unit
class TestCatalogAndProfiles:
    def test_set_catalog_populates_admin(self):
        governor.set_catalog(t.name for t in _sample_tools())
        assert set(governor.list_available()) == {
            "tasks__create-task",
            "tasks__list-users",
            "tasks__get-document",
            "kitchen_pos_partner__menu",
        }

    def test_set_catalog_admin_env_attaches_all_tasks(self, monkeypatch):
        monkeypatch.setenv("SMCP_ATTACH_PROFILE", "admin")
        governor.set_catalog(t.name for t in _sample_tools())
        attached = set(governor.list_attached())
        assert "tasks__list-users" in attached
        assert "tasks__create-task" in attached
        assert governor.GOVERNOR_TOOL_NAME in attached
        # non-tasks tool should not be auto-attached by the admin env path
        assert "kitchen_pos_partner__menu" not in attached

    def test_attach_profile_full_attaches_catalog(self):
        governor.set_catalog(t.name for t in _sample_tools())
        result = governor.attach_profile("full")
        assert result["profile"] == "full"
        assert "tasks__list-users" in result["attached"]
        assert governor.GOVERNOR_TOOL_NAME in result["attached"]

    def test_attach_profile_admin_only_tasks(self):
        governor.set_catalog(t.name for t in _sample_tools())
        # attach_profile returns the attached set at call time (before any
        # later _bootstrap can re-apply the default profile).
        attached = set(governor.attach_profile("admin")["attached"])
        assert "tasks__list-users" in attached
        assert "kitchen_pos_partner__menu" not in attached

    def test_attach_profile_chatter_filters_admin_commands(self):
        governor.set_catalog(t.name for t in _sample_tools())
        attached = set(governor.attach_profile("chatter")["attached"])
        assert "tasks__create-task" in attached
        assert "tasks__get-document" in attached
        assert "tasks__list-users" not in attached

    def test_attach_profile_partner(self):
        governor.set_catalog(t.name for t in _sample_tools())
        attached = set(governor.attach_profile("partner")["attached"])
        assert "kitchen_pos_partner__menu" in attached
        assert "tasks__create-task" not in attached

    def test_attach_profile_unknown_raises(self):
        governor.set_catalog(t.name for t in _sample_tools())
        with pytest.raises(ValueError):
            governor.attach_profile("bogus")


@pytest.mark.unit
class TestAttachDetach:
    def test_attach_unknown_tool_returns_false(self):
        governor.set_catalog(t.name for t in _sample_tools())
        assert governor.attach("not__real") is False

    def test_attach_and_detach_roundtrip(self):
        governor.set_catalog(t.name for t in _sample_tools())
        # Trigger bootstrap (default "full" profile) via a real entry point so
        # subsequent gate calls don't re-bootstrap and clobber our changes.
        assert governor.gate_tool_call("tasks__create-task") is None
        assert governor.detach("tasks__create-task") is True
        assert governor.gate_tool_call("tasks__create-task") is not None
        assert governor.attach("tasks__create-task") is True
        assert governor.gate_tool_call("tasks__create-task") is None

    def test_detach_governor_tool_blocked(self):
        governor.set_catalog(t.name for t in _sample_tools())
        governor.attach_profile("full")
        assert governor.detach(governor.GOVERNOR_TOOL_NAME) is False

    def test_detach_not_attached_returns_false(self):
        governor.set_catalog(t.name for t in _sample_tools())
        governor.attach_profile("chatter")
        assert governor.detach("tasks__list-users") is False

    def test_attach_governor_tool_allowed(self):
        governor.set_catalog(t.name for t in _sample_tools())
        assert governor.attach(governor.GOVERNOR_TOOL_NAME) is True


@pytest.mark.unit
class TestFilterAndBootstrap:
    def test_filter_tools_autopopulates_catalog_and_inserts_governor(self, monkeypatch):
        monkeypatch.setenv("SMCP_ATTACH_PROFILE", "full")
        governor.reset_for_tests()
        # No explicit set_catalog: bootstrap runs on an empty catalog, then
        # filter_tools lazily populates the catalog and re-applies the active
        # full profile so every discovered tool is attached.
        listed = governor.filter_tools(_sample_tools())
        names = [t.name for t in listed]
        assert governor.GOVERNOR_TOOL_NAME in names
        assert "tasks__list-users" in governor.list_available()
        assert "tasks__list-users" in names

    def test_filter_tools_does_not_double_insert_governor(self):
        governor.set_catalog(t.name for t in _sample_tools())
        governor.attach_profile("full")
        listed = governor.filter_tools(_sample_tools() + [governor.governor_tool()])
        assert sum(1 for t in listed if t.name == governor.GOVERNOR_TOOL_NAME) == 1

    def test_bootstrap_from_env_profile(self, monkeypatch):
        monkeypatch.setenv("SMCP_ATTACH_PROFILE", "chatter")
        governor.set_catalog(t.name for t in _sample_tools())
        listed = governor.filter_tools(_sample_tools())
        names = {t.name for t in listed}
        assert "tasks__list-users" not in names

    def test_bootstrap_runs_once(self, monkeypatch):
        monkeypatch.setenv("SMCP_ATTACH_PROFILE", "chatter")
        governor.set_catalog(t.name for t in _sample_tools())
        governor.list_attached()  # triggers bootstrap
        # Change env; bootstrap should not re-run since already bootstrapped
        monkeypatch.setenv("SMCP_ATTACH_PROFILE", "full")
        governor.list_attached()
        assert "tasks__list-users" not in set(governor.list_attached())

    def test_is_attached_governor_always_true(self):
        governor.set_catalog(t.name for t in _sample_tools())
        governor.attach_profile("chatter")
        assert governor.is_attached(governor.GOVERNOR_TOOL_NAME) is True


@pytest.mark.unit
class TestHandleGovernor:
    def test_list_available(self):
        governor.set_catalog(t.name for t in _sample_tools())
        out = json.loads(governor.handle_governor({"action": "list-available"}))
        assert "tasks__create-task" in out["tools"]

    def test_list_attached(self):
        governor.set_catalog(t.name for t in _sample_tools())
        governor.attach_profile("chatter")
        out = json.loads(governor.handle_governor({"action": "list-attached"}))
        assert governor.GOVERNOR_TOOL_NAME in out["tools"]

    def test_attach_via_tools_list(self):
        governor.set_catalog(t.name for t in _sample_tools())
        governor.attach_profile("chatter")
        out = json.loads(governor.handle_governor({"action": "attach", "tools": ["tasks__list-users"]}))
        assert "tasks__list-users" in out["attached"]

    def test_attach_via_single_tool(self):
        governor.set_catalog(t.name for t in _sample_tools())
        governor.attach_profile("chatter")
        out = json.loads(governor.handle_governor({"action": "attach", "tool": "tasks__list-users"}))
        assert "tasks__list-users" in out["attached"]

    def test_detach_via_tools(self):
        governor.set_catalog(t.name for t in _sample_tools())
        governor.attach_profile("full")
        out = json.loads(governor.handle_governor({"action": "detach", "tools": ["tasks__create-task"]}))
        assert "tasks__create-task" in out["detached"]

    def test_attach_profile_action(self):
        governor.set_catalog(t.name for t in _sample_tools())
        out = json.loads(governor.handle_governor({"action": "attach-profile", "profile": "chatter"}))
        assert out["profile"] == "chatter"

    def test_attach_profile_action_default(self):
        governor.set_catalog(t.name for t in _sample_tools())
        out = json.loads(governor.handle_governor({"action": "attach-profile"}))
        assert out["profile"] == "chatter"

    def test_help_no_intent(self):
        out = json.loads(governor.handle_governor({"action": "help"}))
        assert "matches" in out
        assert len(out["matches"]) == 3

    def test_help_with_intent(self):
        out = json.loads(governor.handle_governor({"action": "help", "intent": "document"}))
        assert all("document" in m["intent"] or "document" in m["tool"] for m in out["matches"])

    def test_action_normalizes_underscore(self):
        governor.set_catalog(t.name for t in _sample_tools())
        out = json.loads(governor.handle_governor({"action": "list_available"}))
        assert "tools" in out

    def test_unknown_action(self):
        out = json.loads(governor.handle_governor({"action": "nonsense"}))
        assert "unknown action" in out["error"]


@pytest.mark.unit
class TestGate:
    def test_gate_attached_returns_none(self):
        governor.set_catalog(t.name for t in _sample_tools())
        governor.attach_profile("full")
        assert governor.gate_tool_call("tasks__create-task") is None

    def test_gate_detached_returns_hint(self, monkeypatch):
        # Drive the chatter profile through the env var so _bootstrap applies it.
        monkeypatch.setenv("SMCP_ATTACH_PROFILE", "chatter")
        governor.set_catalog(t.name for t in _sample_tools())
        blocked = governor.gate_tool_call("tasks__list-users")
        payload = json.loads(blocked)
        assert payload["error"] == "tool_not_attached"
        assert governor.GOVERNOR_TOOL_NAME in payload["hint"]


@pytest.mark.unit
class TestProfileConfig:
    def test_no_config_yields_full_only(self, monkeypatch):
        monkeypatch.delenv("SMCP_PROFILES", raising=False)
        monkeypatch.delenv("SMCP_ADMIN_PREFIX", raising=False)
        governor.reset_for_tests()
        governor.set_catalog(t.name for t in _sample_tools())
        assert governor.profile_names() == ["full"]
        attached = set(governor.attach_profile("full")["attached"])
        assert "tasks__create-task" in attached
        assert "kitchen_pos_partner__menu" in attached
        with pytest.raises(ValueError):
            governor.attach_profile("chatter")

    def test_admin_prefix_env_without_config_file(self, monkeypatch):
        monkeypatch.delenv("SMCP_PROFILES", raising=False)
        monkeypatch.setenv("SMCP_ADMIN_PREFIX", "tasks__")
        governor.reset_for_tests()
        governor.set_catalog(t.name for t in _sample_tools())
        attached = set(governor.attach_profile("admin")["attached"])
        assert "tasks__list-users" in attached
        assert "kitchen_pos_partner__menu" not in attached

    def test_load_profiles_from_directory(self, monkeypatch, tmp_path):
        (tmp_path / "a.json").write_text(_PROFILES_FIXTURE.read_text(), encoding="utf-8")
        monkeypatch.setenv("SMCP_PROFILES", str(tmp_path))
        governor.reset_for_tests()
        governor.set_catalog(t.name for t in _sample_tools())
        attached = set(governor.attach_profile("partner")["attached"])
        assert "kitchen_pos_partner__menu" in attached

    def test_invalid_profile_file_raises(self, monkeypatch, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("SMCP_PROFILES", str(bad))
        governor.reset_for_tests()
        with pytest.raises(ValueError, match="failed to load"):
            governor.profile_names()

    def test_glob_profile_mode(self, monkeypatch, tmp_path):
        cfg = {
            "profiles": {
                "pos": {"mode": "glob", "pattern": "kitchen_pos_partner__*"}
            }
        }
        (tmp_path / "pos.json").write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setenv("SMCP_PROFILES", str(tmp_path))
        governor.reset_for_tests()
        governor.set_catalog(t.name for t in _sample_tools())
        attached = set(governor.attach_profile("pos")["attached"]) - {governor.GOVERNOR_TOOL_NAME}
        assert attached == {"kitchen_pos_partner__menu"}

    def test_help_without_config_has_no_product_hints(self, monkeypatch):
        monkeypatch.delenv("SMCP_PROFILES", raising=False)
        governor.reset_for_tests()
        out = json.loads(governor.handle_governor({"action": "help"}))
        assert out["matches"] == []
