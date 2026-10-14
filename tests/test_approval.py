"""Tests for the human approval step.

The most important assertion in this file is the last one: the diff is shown
*before* the question is asked, so a human can never approve blind.
"""

from __future__ import annotations

import pytest

from agent.approval import ApprovalAborted, ask_for_approval
from agent.patch import parse_edits, plan_changes
from agent.workspace import Workspace


@pytest.fixture
def changes(tmp_path):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    workspace = Workspace(tmp_path)
    edits = parse_edits([{"path": "calc.py", "old": "return a - b", "new": "return a + b"}])
    return plan_changes(workspace, edits)


class Recorder:
    """Collects everything written to the output instead of printing it."""

    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, *parts, **_kwargs):
        self.lines.append(" ".join(str(part) for part in parts))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def never_called(_prompt: str) -> str:
    raise AssertionError("the human should not have been asked")


def test_auto_approve_never_asks_the_human(changes):
    assert (
        ask_for_approval(
            changes, auto_approve=True, input_fn=never_called, output_fn=Recorder()
        )
        is True
    )


def test_answering_yes_approves(changes):
    assert ask_for_approval(changes, input_fn=lambda _p: "y", output_fn=Recorder()) is True


def test_answering_no_rejects(changes):
    assert ask_for_approval(changes, input_fn=lambda _p: "n", output_fn=Recorder()) is False


def test_an_empty_answer_rejects(changes):
    assert ask_for_approval(changes, input_fn=lambda _p: "", output_fn=Recorder()) is False


def test_answering_quit_aborts_the_run(changes):
    with pytest.raises(ApprovalAborted, match="Stopped by the user"):
        ask_for_approval(changes, input_fn=lambda _p: "q", output_fn=Recorder())


def test_missing_input_aborts_instead_of_guessing(changes):
    def raise_eof(_prompt: str) -> str:
        raise EOFError

    with pytest.raises(ApprovalAborted, match="Nobody answered"):
        ask_for_approval(changes, input_fn=raise_eof, output_fn=Recorder())


def test_an_unrecognised_answer_is_asked_again(changes):
    answers = iter(["maybe", "y"])
    recorder = Recorder()
    approved = ask_for_approval(
        changes, input_fn=lambda _p: next(answers), output_fn=recorder
    )

    assert approved is True
    assert "Please answer 'y', 'n' or 'q'." in recorder.text


def test_requesting_approval_for_no_changes_is_an_error():
    with pytest.raises(ValueError, match="no changes"):
        ask_for_approval(
            [], auto_approve=True, input_fn=never_called, output_fn=Recorder()
        )


def test_the_diff_is_shown_before_the_question(changes):
    recorder = Recorder()
    ask_for_approval(changes, auto_approve=True, input_fn=never_called, output_fn=recorder)

    text = recorder.text
    assert "PROPOSED CHANGES (1 file(s))" in text
    assert "-    return a - b" in text
    assert "+    return a + b" in text
    assert text.index("PROPOSED CHANGES") < text.index("Auto-approve is enabled")
