"""Tests for turning a proposed fix into a diff and applying it."""

from __future__ import annotations

import pytest

from agent.patch import PatchError, apply_changes, parse_edits, plan_changes
from agent.workspace import Workspace


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n\n\ndef unused():\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "repeat.py").write_text("value = 1\nvalue = 1\n", encoding="utf-8")
    return Workspace(tmp_path)


# -- parse_edits -------------------------------------------------------------

def test_parse_edits_accepts_a_valid_proposal():
    edits = parse_edits([{"path": "calc.py", "old": "a - b", "new": "a + b"}])
    assert len(edits) == 1
    assert edits[0].path == "calc.py"
    assert edits[0].replace_all is False


def test_parse_edits_rejects_an_empty_list():
    with pytest.raises(PatchError, match="non-empty list"):
        parse_edits([])


def test_parse_edits_rejects_a_missing_path():
    with pytest.raises(PatchError, match="'path'"):
        parse_edits([{"old": "a", "new": "b"}])


def test_parse_edits_rejects_a_missing_new_field():
    with pytest.raises(PatchError, match="'new'"):
        parse_edits([{"path": "calc.py", "old": "a"}])


def test_parse_edits_rejects_a_no_op_edit():
    with pytest.raises(PatchError, match="does not change anything"):
        parse_edits([{"path": "calc.py", "old": "same", "new": "same"}])


def test_parse_edits_normalises_backslashes_in_paths():
    edits = parse_edits([{"path": "pkg\\mod.py", "old": "a", "new": "b"}])
    assert edits[0].path == "pkg/mod.py"


# -- plan_changes ------------------------------------------------------------

def test_plan_builds_a_unified_diff(workspace):
    edits = parse_edits([{"path": "calc.py", "old": "return a - b", "new": "return a + b"}])
    changes = plan_changes(workspace, edits)

    assert len(changes) == 1
    assert "--- a/calc.py" in changes[0].diff
    assert "+++ b/calc.py" in changes[0].diff
    assert "-    return a - b" in changes[0].diff
    assert "+    return a + b" in changes[0].diff
    # Planning must not write anything yet.
    assert "a - b" in workspace.read_text("calc.py")


def test_plan_rejects_an_old_string_that_is_not_present(workspace):
    edits = parse_edits([{"path": "calc.py", "old": "return a * b", "new": "return a + b"}])
    with pytest.raises(PatchError, match="was not found"):
        plan_changes(workspace, edits)


def test_plan_rejects_an_ambiguous_old_string(workspace):
    edits = parse_edits([{"path": "repeat.py", "old": "value = 1", "new": "value = 2"}])
    with pytest.raises(PatchError, match="appears 2 times"):
        plan_changes(workspace, edits)


def test_plan_allows_an_ambiguous_match_when_replace_all_is_set(workspace):
    edits = parse_edits(
        [{"path": "repeat.py", "old": "value = 1", "new": "value = 2", "replace_all": True}]
    )
    changes = plan_changes(workspace, edits)
    assert changes[0].updated == "value = 2\nvalue = 2\n"


def test_parse_edits_rejects_an_empty_old(workspace):
    # An empty 'old' would mean "write the whole file", which the agent must not
    # be able to do: it can only replace text it has quoted from the file.
    with pytest.raises(PatchError, match="non-empty 'old'"):
        parse_edits([{"path": "brand_new.py", "old": "", "new": "print('hi')\n"}])


def test_plan_refuses_to_edit_a_missing_file(workspace):
    edits = parse_edits([{"path": "ghost.py", "old": "x", "new": "y"}])
    with pytest.raises(PatchError, match="File not found"):
        plan_changes(workspace, edits)


def test_plan_applies_several_edits_to_the_same_file_in_order(workspace):
    edits = parse_edits(
        [
            {"path": "calc.py", "old": "return a - b", "new": "return a + b"},
            {"path": "calc.py", "old": "return 1", "new": "return 2"},
        ]
    )
    changes = plan_changes(workspace, edits)
    assert len(changes) == 1
    assert "return a + b" in changes[0].updated
    assert "return 2" in changes[0].updated


# -- apply_changes -----------------------------------------------------------

def test_apply_writes_only_after_being_called(workspace):
    edits = parse_edits([{"path": "calc.py", "old": "return a - b", "new": "return a + b"}])
    changes = plan_changes(workspace, edits)

    written = apply_changes(workspace, changes)

    assert written == ["calc.py"]
    assert "return a + b" in workspace.read_text("calc.py")



