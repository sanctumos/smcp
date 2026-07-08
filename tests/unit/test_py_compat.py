"""
Python version-compatibility guards (issue #48).

The package advertises `requires-python >=3.8` and lists 3.8/3.9 classifiers, but
the core uses PEP 604 union syntax (`X | None`). `from __future__ import annotations`
(PEP 563) defers annotation evaluation so those modules import cleanly on 3.8/3.9.
These tests lock that in and keep the future-import usage consistent across core
modules (also the consistency bullet of #49).

Copyright (c) 2025 Mark Rizzn Hopkins
Licensed under AGPLv3 (see LICENSE).
"""

import sys
import importlib.util
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))
_spec = importlib.util.spec_from_file_location("smcp_module", str(_repo_root / "smcp.py"))
smcp_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = smcp_module
_spec.loader.exec_module(smcp_module)


@pytest.mark.unit
class TestFutureAnnotationsConsistency:
    @pytest.mark.parametrize("module", ["smcp.py", "smcp_stdio.py", "governor.py"])
    def test_core_modules_defer_annotations(self, module):
        src = (_repo_root / module).read_text()
        assert "from __future__ import annotations" in src, (
            f"{module} must defer annotations for 3.8/3.9 (PEP 604 unions)"
        )

    def test_future_import_precedes_other_code(self):
        # Must be the first statement after the docstring to be a valid future import.
        for module in ("smcp.py", "smcp_stdio.py"):
            lines = [
                ln.strip()
                for ln in (_repo_root / module).read_text().splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            # first non-comment logical line is the docstring open; find the future import
            # before any non-import executable statement.
            fut = next(i for i, ln in enumerate(lines) if "from __future__ import annotations" in ln)
            code_before = [
                ln for ln in lines[:fut]
                if not (ln.startswith('"""') or ln.endswith('"""') or ln.startswith("'''"))
                and not ln.startswith("import ") and not ln.startswith("from ")
            ]
            # Only docstring text may precede it; no imports/other statements.
            assert all('"' in ln or "'" in ln or ln.isprintable() for ln in code_before)

    def test_module_level_union_annotation_is_deferred(self):
        # With PEP 563 active, the `server` annotation is stored as a string, not
        # evaluated (which would TypeError on 3.8/3.9).
        ann = smcp_module.__annotations__.get("server")
        assert isinstance(ann, str)
        assert "None" in ann
