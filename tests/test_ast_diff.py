"""
test_ast_diff.py — Stage 2 tests for structural_diff.
"""
from __future__ import annotations

import pytest

from tenet.diffing.ast_diff import structural_diff

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_FOO = """\
def foo(x: int) -> int:
    return x + 1

def bar(name: str) -> str:
    return f"Hello, {name}"
"""

SIG_CHANGED_FOO = """\
def foo(x: int, y: str) -> int:
    return x + 1

def bar(name: str) -> str:
    return f"Hello, {name}"
"""

BODY_CHANGED_FOO = """\
def foo(x: int) -> int:
    result = x * 2
    return result

def bar(name: str) -> str:
    return f"Hello, {name}"
"""

WITH_CLASS = """\
class Animal:
    def speak(self) -> str:
        return "..."

class Dog(Animal):
    def speak(self) -> str:
        return "Woof"
"""

ADDED_METHOD = """\
class Animal:
    def speak(self) -> str:
        return "..."

    def breathe(self) -> None:
        pass

class Dog(Animal):
    def speak(self) -> str:
        return "Woof"
"""

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStructuralDiff:
    def test_no_changes_returns_empty(self):
        changes = structural_diff(BASE_FOO, BASE_FOO, "python")
        assert changes == []

    def test_signature_changed_detected(self):
        changes = structural_diff(BASE_FOO, SIG_CHANGED_FOO, "python")
        sig_changes = [c for c in changes if c.change_type == "signature_changed"]
        assert len(sig_changes) >= 1
        foo_change = next((c for c in sig_changes if c.node_name == "foo"), None)
        assert foo_change is not None, "foo signature change not detected"
        assert "y: str" in foo_change.new_signature

    def test_signature_change_does_not_flag_unchanged_body(self):
        """Renaming a param should report signature_changed but NOT body_changed for foo."""
        changes = structural_diff(BASE_FOO, SIG_CHANGED_FOO, "python")
        # bar should not appear in changes at all
        bar_changes = [c for c in changes if c.node_name == "bar"]
        assert bar_changes == [], f"bar unexpectedly in changes: {bar_changes}"

    def test_body_changed_detected(self):
        changes = structural_diff(BASE_FOO, BODY_CHANGED_FOO, "python")
        body_changes = [c for c in changes if c.change_type == "body_changed"]
        assert any(c.node_name == "foo" for c in body_changes)

    def test_body_change_does_not_flag_unchanged_function(self):
        """Changing foo body should leave bar unchanged."""
        changes = structural_diff(BASE_FOO, BODY_CHANGED_FOO, "python")
        bar_changes = [c for c in changes if c.node_name == "bar"]
        assert bar_changes == []

    def test_added_node_detected(self):
        changes = structural_diff(WITH_CLASS, ADDED_METHOD, "python")
        added = [c for c in changes if c.change_type == "added"]
        assert any("breathe" in c.node_name for c in added)

    def test_removed_node_detected(self):
        changes = structural_diff(ADDED_METHOD, WITH_CLASS, "python")
        removed = [c for c in changes if c.change_type == "removed"]
        assert any("breathe" in c.node_name for c in removed)

    def test_old_and_new_signature_populated(self):
        changes = structural_diff(BASE_FOO, SIG_CHANGED_FOO, "python")
        foo_change = next((c for c in changes if c.node_name == "foo"), None)
        assert foo_change is not None
        assert foo_change.old_signature is not None
        assert foo_change.new_signature is not None
        assert foo_change.old_signature != foo_change.new_signature

    def test_empty_old_content_all_added(self):
        changes = structural_diff("", BASE_FOO, "python")
        added = [c for c in changes if c.change_type == "added"]
        assert len(added) >= 2  # foo and bar should both be 'added'

    def test_empty_new_content_all_removed(self):
        changes = structural_diff(BASE_FOO, "", "python")
        removed = [c for c in changes if c.change_type == "removed"]
        assert len(removed) >= 2  # foo and bar should both be 'removed'

    def test_summary_field_is_non_empty(self):
        changes = structural_diff(BASE_FOO, SIG_CHANGED_FOO, "python")
        for c in changes:
            assert c.summary, f"Empty summary for change {c.node_name}"

    def test_param_rename_is_signature_change_not_body_change(self):
        """Specifically: renaming a parameter should be signature_changed, never body_changed."""
        old = "def process(data: list) -> None:\n    pass\n"
        new = "def process(items: list) -> None:\n    pass\n"
        changes = structural_diff(old, new, "python")
        process_changes = [c for c in changes if c.node_name == "process"]
        assert len(process_changes) >= 1
        change_types = {c.change_type for c in process_changes}
        assert "signature_changed" in change_types
        assert "body_changed" not in change_types
