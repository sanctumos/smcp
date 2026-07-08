"""
Unit tests for the SMCP session attach governor (governor.py).

Covers the full public surface: catalog/profile management, attach/detach
guards, tool filtering, the sanctum__tools handler actions, and call gating.

Issue #46: each test constructs its own ``Governor`` instance — no process-
global attach state, so no autouse reset fixture is required.

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import json
import os
from pathlib import Path

import pytest

from governor import GOVERNOR_TOOL_NAME, Governor
from mcp.types import Tool

_PROFILES_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "governor_profiles_sanctum.json"


@pytest.fixture
def gov(monkeypatch):
    """Fresh Governor with the Sanctum tasks/partner profile fixture (#45)."""
    monkeypatch.setenv("SMCP_PROFILES", str(_PROFILES_FIXTURE))
    monkeypatch.delenv("SMCP_ATTACH_PROFILE", raising=False)
    monkeypatch.delenv("SMCP_ADMIN_PREFIX", raising=False)
    return Governor()


def _sample_tools():
    return [
        Tool(name="tasks__create-task", description="create", inputSchema={"type": "object"}),
        Tool(name="tasks__list-users", description="admin", inputSchema={"type": "object"}),
        Tool(name="tasks__get-document", description="doc", inputSchema={"type": "object"}),
        Tool(name="kitchen_pos_partner__menu", description="menu", inputSchema={"type": "object"}),
    ]


@pytest.mark.unit
class TestCatalogAndProfiles:
    def test_set_catalog_populates_admin(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        assert set(gov.list_available()) == {
            "tasks__create-task",
            "tasks__list-users",
            "tasks__get-document",
            "kitchen_pos_partner__menu",
        }

    def test_set_catalog_admin_env_attaches_all_tasks(self, monkeypatch, gov):
        monkeypatch.setenv("SMCP_ATTACH_PROFILE", "admin")
        gov.set_catalog(t.name for t in _sample_tools())
        attached = set(gov.list_attached())
        assert "tasks__list-users" in attached
        assert "tasks__create-task" in attached
        assert GOVERNOR_TOOL_NAME in attached
        # non-tasks tool should not be auto-attached by the admin env path
        assert "kitchen_pos_partner__menu" not in attached

    def test_attach_profile_full_attaches_catalog(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        result = gov.attach_profile("full")
        assert result["profile"] == "full"
        assert "tasks__list-users" in result["attached"]
        assert GOVERNOR_TOOL_NAME in result["attached"]

    def test_attach_profile_admin_only_tasks(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        attached = set(gov.attach_profile("admin")["attached"])
        assert "tasks__list-users" in attached
        assert "kitchen_pos_partner__menu" not in attached

    def test_attach_profile_chatter_filters_admin_commands(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        attached = set(gov.attach_profile("chatter")["attached"])
        assert "tasks__create-task" in attached
        assert "tasks__get-document" in attached
        assert "tasks__list-users" not in attached

    def test_attach_profile_partner(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        attached = set(gov.attach_profile("partner")["attached"])
        assert "kitchen_pos_partner__menu" in attached
        assert "tasks__create-task" not in attached

    def test_attach_profile_unknown_raises(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        with pytest.raises(ValueError):
            gov.attach_profile("bogus")


@pytest.mark.unit
class TestAttachDetach:
    def test_attach_unknown_tool_returns_false(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        assert gov.attach("not__real") is False

    def test_attach_and_detach_roundtrip(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        # Trigger bootstrap (default "full" / chatter from fixture) via a real
        # entry point so subsequent gate calls don't re-bootstrap oddly.
        assert gov.gate_tool_call("tasks__create-task") is None
        assert gov.detach("tasks__create-task") is True
        assert gov.gate_tool_call("tasks__create-task") is not None
        assert gov.attach("tasks__create-task") is True
        assert gov.gate_tool_call("tasks__create-task") is None

    def test_detach_governor_tool_blocked(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        gov.attach_profile("full")
        assert gov.detach(GOVERNOR_TOOL_NAME) is False

    def test_detach_not_attached_returns_false(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        gov.attach_profile("chatter")
        assert gov.detach("tasks__list-users") is False

    def test_attach_governor_tool_allowed(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        assert gov.attach(GOVERNOR_TOOL_NAME) is True


@pytest.mark.unit
class TestFilterAndBootstrap:
    def test_filter_tools_autopopulates_catalog_and_inserts_governor(self, monkeypatch):
        monkeypatch.setenv("SMCP_PROFILES", str(_PROFILES_FIXTURE))
        monkeypatch.setenv("SMCP_ATTACH_PROFILE", "full")
        g = Governor()
        listed = g.filter_tools(_sample_tools())
        names = [t.name for t in listed]
        assert GOVERNOR_TOOL_NAME in names
        assert "tasks__list-users" in g.list_available()
        assert "tasks__list-users" in names

    def test_filter_tools_does_not_double_insert_governor(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        gov.attach_profile("full")
        listed = gov.filter_tools(_sample_tools() + [gov.governor_tool()])
        assert sum(1 for t in listed if t.name == GOVERNOR_TOOL_NAME) == 1

    def test_bootstrap_from_env_profile(self, monkeypatch):
        monkeypatch.setenv("SMCP_PROFILES", str(_PROFILES_FIXTURE))
        monkeypatch.setenv("SMCP_ATTACH_PROFILE", "chatter")
        g = Governor()
        g.set_catalog(t.name for t in _sample_tools())
        listed = g.filter_tools(_sample_tools())
        names = {t.name for t in listed}
        assert "tasks__list-users" not in names

    def test_bootstrap_runs_once(self, monkeypatch):
        monkeypatch.setenv("SMCP_PROFILES", str(_PROFILES_FIXTURE))
        monkeypatch.setenv("SMCP_ATTACH_PROFILE", "chatter")
        g = Governor()
        g.set_catalog(t.name for t in _sample_tools())
        g.list_attached()  # triggers bootstrap
        # Change env; bootstrap should not re-run since already bootstrapped
        monkeypatch.setenv("SMCP_ATTACH_PROFILE", "full")
        g.list_attached()
        assert "tasks__list-users" not in set(g.list_attached())

    def test_is_attached_governor_always_true(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        gov.attach_profile("chatter")
        assert gov.is_attached(GOVERNOR_TOOL_NAME) is True


@pytest.mark.unit
class TestHandleGovernor:
    def test_list_available(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        out = json.loads(gov.handle({"action": "list-available"}))
        assert "tasks__create-task" in out["tools"]

    def test_list_attached(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        gov.attach_profile("chatter")
        out = json.loads(gov.handle({"action": "list-attached"}))
        assert GOVERNOR_TOOL_NAME in out["tools"]

    def test_attach_via_tools_list(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        gov.attach_profile("chatter")
        out = json.loads(gov.handle({"action": "attach", "tools": ["tasks__list-users"]}))
        assert "tasks__list-users" in out["attached"]

    def test_attach_via_single_tool(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        gov.attach_profile("chatter")
        out = json.loads(gov.handle({"action": "attach", "tool": "tasks__list-users"}))
        assert "tasks__list-users" in out["attached"]

    def test_detach_via_tools(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        gov.attach_profile("full")
        out = json.loads(gov.handle({"action": "detach", "tools": ["tasks__create-task"]}))
        assert "tasks__create-task" in out["detached"]

    def test_attach_profile_action(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        out = json.loads(gov.handle({"action": "attach-profile", "profile": "chatter"}))
        assert out["profile"] == "chatter"

    def test_attach_profile_action_default(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        out = json.loads(gov.handle({"action": "attach-profile"}))
        assert out["profile"] == "chatter"

    def test_help_no_intent(self, gov):
        out = json.loads(gov.handle({"action": "help"}))
        assert "matches" in out
        assert len(out["matches"]) == 3

    def test_help_with_intent(self, gov):
        out = json.loads(gov.handle({"action": "help", "intent": "document"}))
        assert all("document" in m["intent"] or "document" in m["tool"] for m in out["matches"])

    def test_action_normalizes_underscore(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        out = json.loads(gov.handle({"action": "list_available"}))
        assert "tools" in out

    def test_unknown_action(self, gov):
        out = json.loads(gov.handle({"action": "nonsense"}))
        assert "unknown action" in out["error"]


@pytest.mark.unit
class TestGate:
    def test_gate_attached_returns_none(self, gov):
        gov.set_catalog(t.name for t in _sample_tools())
        gov.attach_profile("full")
        assert gov.gate_tool_call("tasks__create-task") is None

    def test_gate_detached_returns_hint(self, monkeypatch):
        monkeypatch.setenv("SMCP_PROFILES", str(_PROFILES_FIXTURE))
        monkeypatch.setenv("SMCP_ATTACH_PROFILE", "chatter")
        g = Governor()
        g.set_catalog(t.name for t in _sample_tools())
        blocked = g.gate_tool_call("tasks__list-users")
        payload = json.loads(blocked)
        assert payload["error"] == "tool_not_attached"
        assert GOVERNOR_TOOL_NAME in payload["hint"]


@pytest.mark.unit
class TestProfileConfig:
    def test_no_config_yields_full_only(self, monkeypatch):
        monkeypatch.delenv("SMCP_PROFILES", raising=False)
        monkeypatch.delenv("SMCP_ADMIN_PREFIX", raising=False)
        g = Governor()
        g.set_catalog(t.name for t in _sample_tools())
        assert g.profile_names() == ["full"]
        attached = set(g.attach_profile("full")["attached"])
        assert "tasks__create-task" in attached
        assert "kitchen_pos_partner__menu" in attached
        with pytest.raises(ValueError):
            g.attach_profile("chatter")

    def test_admin_prefix_env_without_config_file(self, monkeypatch):
        monkeypatch.delenv("SMCP_PROFILES", raising=False)
        monkeypatch.setenv("SMCP_ADMIN_PREFIX", "tasks__")
        g = Governor()
        g.set_catalog(t.name for t in _sample_tools())
        attached = set(g.attach_profile("admin")["attached"])
        assert "tasks__list-users" in attached
        assert "kitchen_pos_partner__menu" not in attached

    def test_load_profiles_from_directory(self, monkeypatch, tmp_path):
        (tmp_path / "a.json").write_text(_PROFILES_FIXTURE.read_text(), encoding="utf-8")
        monkeypatch.setenv("SMCP_PROFILES", str(tmp_path))
        g = Governor()
        g.set_catalog(t.name for t in _sample_tools())
        attached = set(g.attach_profile("partner")["attached"])
        assert "kitchen_pos_partner__menu" in attached

    def test_invalid_profile_file_raises(self, monkeypatch, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("SMCP_PROFILES", str(bad))
        g = Governor()
        with pytest.raises(ValueError, match="failed to load"):
            g.profile_names()

    def test_glob_profile_mode(self, monkeypatch, tmp_path):
        cfg = {
            "profiles": {
                "pos": {"mode": "glob", "pattern": "kitchen_pos_partner__*"}
            }
        }
        (tmp_path / "pos.json").write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setenv("SMCP_PROFILES", str(tmp_path))
        g = Governor()
        g.set_catalog(t.name for t in _sample_tools())
        attached = set(g.attach_profile("pos")["attached"]) - {GOVERNOR_TOOL_NAME}
        assert attached == {"kitchen_pos_partner__menu"}

    def test_help_without_config_has_no_product_hints(self, monkeypatch):
        monkeypatch.delenv("SMCP_PROFILES", raising=False)
        g = Governor()
        out = json.loads(g.handle({"action": "help"}))
        assert out["matches"] == []


@pytest.mark.unit
class TestIsolation:
    def test_two_governors_do_not_cross_talk(self, monkeypatch):
        monkeypatch.setenv("SMCP_PROFILES", str(_PROFILES_FIXTURE))
        a = Governor()
        b = Governor()
        a.set_catalog(t.name for t in _sample_tools())
        a.attach_profile("chatter")
        b.set_catalog(t.name for t in _sample_tools())
        b.attach_profile("full")
        assert "tasks__list-users" not in set(a.list_attached())
        assert "tasks__list-users" in set(b.list_attached())
        a.detach("tasks__create-task")
        assert "tasks__create-task" in set(b.list_attached())
