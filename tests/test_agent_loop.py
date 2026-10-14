"""End-to-end tests for the main loop in ``agent/agent.py``.

The model is replaced by the mock provider — a scripted list of replies — so the
*real* loop is exercised, with the real tools, real diffs, real approval and real
pytest, but without a network connection or an API key.
"""

from __future__ import annotations

import pytest

from agent.agent import run_agent
from agent.llm import LLMError

TASK = "The tests are failing. Find and fix the bug."

SEARCH = {"thought": "find the calculator", "tool": "search_code", "args": {"query": "def add"}}
READ = {"thought": "read it", "tool": "read_file", "args": {"path": "calc.py"}}
FIX_GOOD = {
    "thought": "the operator is wrong",
    "action": "propose_fix",
    "summary": "use + instead of -",
    "edits": [{"path": "calc.py", "old": "return a - b", "new": "return a + b"}],
}
FIX_BAD = {
    "thought": "maybe it should multiply",
    "action": "propose_fix",
    "summary": "use * instead of -",
    "edits": [{"path": "calc.py", "old": "return a - b", "new": "return a * b"}],
}
FIX_FROM_BAD = {
    "thought": "it should add",
    "action": "propose_fix",
    "summary": "use + instead of *",
    "edits": [{"path": "calc.py", "old": "return a * b", "new": "return a + b"}],
}
DONE = {"thought": "nothing more to do", "action": "done", "message": "Stopping."}


def noop(*_args, **_kwargs):
    """Discard the agent's running commentary."""


def run_with(config, answer: str = "y"):
    """Run the loop, answering the approval prompt with ``answer``."""
    return run_agent(TASK, config, input_fn=lambda _prompt: answer, output=noop)


def calc(workspace):
    return (workspace / "calc.py").read_text(encoding="utf-8")


# -- happy path --------------------------------------------------------------

def test_agent_investigates_proposes_and_fixes_the_bug(
    buggy_workspace, make_config, write_mock_script
):
    config = make_config(
        workspace=buggy_workspace,
        mock_responses_file=write_mock_script([SEARCH, READ, FIX_GOOD]),
    )
    outcome = run_with(config)

    assert outcome.status == "fixed"
    assert outcome.attempts == 1
    assert outcome.changed_files == ["calc.py"]
    assert outcome.test_result is not None and outcome.test_result.passed
    assert "return a + b" in calc(buggy_workspace)


def test_auto_approve_skips_the_prompt(
    buggy_workspace, make_config, write_mock_script
):
    # This is the path the CLI's --yes flag takes.
    config = make_config(
        workspace=buggy_workspace,
        mock_responses_file=write_mock_script([READ, FIX_GOOD]),
        auto_approve=True,
    )
    outcome = run_with(config)

    assert outcome.status == "fixed"
    assert "return a + b" in calc(buggy_workspace)


def test_agent_recovers_from_a_malformed_model_reply(
    buggy_workspace, make_config, write_mock_script
):
    replies = ["I am not JSON at all, sorry!", SEARCH, READ, FIX_GOOD]
    config = make_config(
        workspace=buggy_workspace, mock_responses_file=write_mock_script(replies)
    )
    outcome = run_with(config)

    assert outcome.status == "fixed"
    assert "return a + b" in calc(buggy_workspace)


def test_agent_corrects_a_bad_edit_reference_without_burning_an_attempt(
    buggy_workspace, make_config, write_mock_script
):
    # The first proposal quotes text that is not in the file, so the planner
    # rejects it; the model then reads the file and tries again.
    bad_reference = {
        "thought": "guess",
        "action": "propose_fix",
        "summary": "guess",
        "edits": [{"path": "calc.py", "old": "return a ** b", "new": "return a + b"}],
    }
    config = make_config(
        workspace=buggy_workspace,
        mock_responses_file=write_mock_script([bad_reference, READ, FIX_GOOD]),
    )
    outcome = run_with(config)

    assert outcome.status == "fixed"
    assert outcome.attempts == 1


# -- retry loop --------------------------------------------------------------

def test_agent_retries_after_a_fix_that_fails_the_tests(
    buggy_workspace, make_config, write_mock_script
):
    replies = [FIX_BAD, SEARCH, READ, FIX_FROM_BAD]
    config = make_config(
        workspace=buggy_workspace,
        mock_responses_file=write_mock_script(replies),
        max_attempts=3,
    )
    outcome = run_with(config)

    assert outcome.status == "fixed"
    assert outcome.attempts == 2
    assert outcome.changed_files == ["calc.py"]  # listed once, not once per attempt
    assert "return a + b" in calc(buggy_workspace)


def test_the_failure_output_is_sent_back_to_the_model(
    buggy_workspace, make_config, write_mock_script, monkeypatch
):
    """Requirement 7: the model must be shown *why* its fix failed."""
    from agent.llm import LLM

    config = make_config(
        workspace=buggy_workspace,
        mock_responses_file=write_mock_script([FIX_BAD, DONE]),
        max_attempts=2,
    )

    # Wrap the model so we can see the conversation it was given.
    conversations: list[list[dict]] = []
    real_complete = LLM.complete

    def record_conversation(self, messages):
        conversations.append(list(messages))
        return real_complete(self, messages)

    monkeypatch.setattr(LLM, "complete", record_conversation)
    outcome = run_with(config)

    assert outcome.status == "done"
    # The second attempt was asked for after a failed test run, and the last
    # thing it was told is that failure.
    failure_message = conversations[-1][-1]["content"]
    assert "did NOT pass" in failure_message
    assert "test_add" in failure_message


def test_agent_gives_up_when_the_retry_limit_is_reached(
    buggy_workspace, make_config, write_mock_script
):
    config = make_config(
        workspace=buggy_workspace,
        mock_responses_file=write_mock_script([FIX_BAD]),
        max_attempts=1,
    )
    outcome = run_with(config)

    assert outcome.status == "gave_up"
    assert outcome.attempts == 1
    assert outcome.test_result is not None and not outcome.test_result.passed


def test_agent_stops_when_it_runs_out_of_steps(
    buggy_workspace, make_config, write_mock_script
):
    # The model only ever searches, never proposes a fix.
    config = make_config(
        workspace=buggy_workspace,
        mock_responses_file=write_mock_script([SEARCH] * 12),
        max_attempts=1,
        max_tool_calls=3,
    )
    outcome = run_with(config)

    assert outcome.status == "gave_up"
    assert outcome.changed_files == []


# -- approval ----------------------------------------------------------------

def test_nothing_is_written_when_the_human_rejects_the_diff(
    buggy_workspace, make_config, write_mock_script
):
    original = calc(buggy_workspace)
    config = make_config(
        workspace=buggy_workspace, mock_responses_file=write_mock_script([FIX_GOOD, DONE])
    )
    outcome = run_with(config, answer="n")

    assert outcome.status == "done"
    assert outcome.changed_files == []
    assert calc(buggy_workspace) == original


def test_agent_can_be_stopped_at_the_approval_prompt(
    buggy_workspace, make_config, write_mock_script
):
    original = calc(buggy_workspace)
    config = make_config(
        workspace=buggy_workspace, mock_responses_file=write_mock_script([FIX_GOOD])
    )
    outcome = run_with(config, answer="q")

    assert outcome.status == "aborted"
    assert calc(buggy_workspace) == original


def test_dry_run_shows_the_diff_but_writes_nothing(
    buggy_workspace, make_config, write_mock_script
):
    original = calc(buggy_workspace)
    config = make_config(
        workspace=buggy_workspace,
        mock_responses_file=write_mock_script([READ, FIX_GOOD]),
        dry_run=True,
    )
    outcome = run_with(config)

    assert outcome.status == "dry_run"
    assert outcome.changed_files == []
    assert calc(buggy_workspace) == original


# -- misc --------------------------------------------------------------------

def test_agent_reports_a_done_action(buggy_workspace, make_config, write_mock_script):
    config = make_config(
        workspace=buggy_workspace, mock_responses_file=write_mock_script([DONE])
    )
    outcome = run_with(config)

    assert outcome.status == "done"
    assert outcome.message == "Stopping."


def test_agent_rejects_an_empty_task(make_config, write_mock_script):
    config = make_config(mock_responses_file=write_mock_script([DONE]))
    with pytest.raises(ValueError, match="must not be empty"):
        run_agent("   ", config, output=noop)


def test_exhausting_the_mock_script_is_reported(
    buggy_workspace, make_config, write_mock_script
):
    # Only one reply is scripted, but the agent asks again after the tool result.
    config = make_config(
        workspace=buggy_workspace, mock_responses_file=write_mock_script([SEARCH])
    )
    with pytest.raises(LLMError, match="ran out"):
        run_with(config)
