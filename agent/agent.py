"""The main agent loop — read this file first.

The whole agent is the single function :func:`run_agent` below. One run follows
this cycle (``max_attempts`` is the retry limit)::

    1. the model asks for a tool  (search / read)
         -> the tool result goes back into the conversation
    2. the model proposes a small edit
         -> a diff is built, but nothing on disk has changed yet
         -> you reject  -> the model is told, and may try again (same attempt)
         -> you approve -> the files are written
                        -> the tests run, and the result goes back to the model
                             -> tests pass -> finished
                             -> tests fail -> next attempt (up to max_attempts)

The model can only *look* at the code (see ``agent/tools.py``) and *propose*
edits. It never writes a file and never runs a command: every write needs your
approval, and the only command that ever runs is your ``TEST_COMMAND``.

Every other module is a detail that this function calls: the model in `llm.py`,
the tools in `tools.py`, the diff in `patch.py`, the question in `approval.py`,
and the tests in `test_runner.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .approval import ApprovalAborted, ask_for_approval
from .llm import LLM
from .patch import PatchError, apply_changes, plan_changes
from .protocol import (
    DONE,
    TOOL_ACTION,
    ProtocolError,
    build_system_prompt,
    parse_action,
)
from .test_runner import TestResult, run_tests, validate_command
from .tools import run_tool
from .workspace import Workspace, WorkspaceError


@dataclass
class AgentOutcome:
    """What happened when the run finished."""

    status: str  # "fixed" | "done" | "gave_up" | "aborted" | "dry_run"
    attempts: int
    message: str = ""
    changed_files: list[str] = field(default_factory=list)
    test_result: TestResult | None = None


def run_agent(task: str, config, *, input_fn=input, output=print) -> AgentOutcome:
    """Work on ``task`` until the tests pass, you stop it, or it gives up.

    ``input_fn`` and ``output`` are the approval prompt and the transcript; they
    are parameters so tests can run the loop without a human.
    """
    if not task or not task.strip():
        raise ValueError("The coding task must not be empty.")

    # Fail before spending any model calls on a run that could never reach the tests.
    validate_command(config.test_command)

    workspace = Workspace(config.workspace)
    llm = LLM(config)

    output("AI Coding Agent")
    output(f"  model    : {config.describe_llm()}")
    output(f"  workspace: {workspace.root}")
    output(f"  tests    : {config.test_command}")
    output(f"  attempts : {config.max_attempts}")

    # The whole conversation with the model. Everything it sees is in this list.
    messages = [
        {
            "role": "system",
            "content": build_system_prompt(str(workspace.root), config.test_command),
        },
        {
            "role": "user",
            "content": (
                f"TASK: {task}\n\n"
                "Work step by step: search the workspace for code related to this task, "
                "read the relevant files, then propose the smallest fix that makes the "
                "tests pass."
            ),
        },
    ]

    changed_files: list[str] = []
    last_test: TestResult | None = None

    for attempt in range(1, config.max_attempts + 1):
        output("")
        output(f"===== attempt {attempt} of {config.max_attempts} =====")

        fix_applied = False

        # One attempt: let the model investigate, then propose an edit.
        for step in range(1, config.max_tool_calls + 1):
            output(f"--- step {step} ---")

            # 1. Ask the model what to do next, and remember its reply.
            reply = llm.complete(messages)
            messages.append({"role": "assistant", "content": reply})
            try:
                action = parse_action(reply)
            except ProtocolError as exc:
                output(f"[reply not understood] {exc}")
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"I could not understand your last reply: {exc}\n"
                            "Reply with exactly one JSON object, for example "
                            '{"thought": "...", "tool": "search_code", "args": {"query": "..."}}.'
                        ),
                    }
                )
                continue

            if action.thought:
                output(f"thought: {action.thought}")

            # 2. The model may decide it is finished.
            if action.kind == DONE:
                output(f"Model stopped: {action.message or '(no message)'}")
                return AgentOutcome("done", attempt, action.message, changed_files, last_test)

            # 3. The model may look at the code, as often as it likes.
            if action.kind == TOOL_ACTION:
                try:
                    result = run_tool(workspace, action.tool, action.args)
                except (ValueError, WorkspaceError) as exc:
                    # Hand the problem back to the model instead of crashing.
                    result = f"ERROR: {exc}"
                    output(f"[tool error] {exc}")
                else:
                    output(f"{action.tool} ->\n{result}")
                messages.append(
                    {"role": "user", "content": f"TOOL RESULT from {action.tool}:\n{result}"}
                )
                continue

            # 4. Otherwise the model is proposing an edit. Build the diff in memory.
            try:
                changes = plan_changes(workspace, action.edits)
            except PatchError as exc:
                output(f"[edit rejected] {exc}")
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your edits were rejected: {exc}\n"
                            "Read the file again and copy the exact text into 'old'."
                        ),
                    }
                )
                continue

            output(f"Proposed fix: {action.summary or '(no summary)'}")

            # 5. Ask the human to approve. Nothing has been written yet.
            try:
                approved = ask_for_approval(
                    changes,
                    auto_approve=config.auto_approve,
                    input_fn=input_fn,
                    output_fn=output,
                )
            except ApprovalAborted as exc:
                output(str(exc))
                return AgentOutcome("aborted", attempt, str(exc), changed_files, last_test)

            if not approved:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The human rejected your proposed changes, so nothing was "
                            "written. Think again and propose a different, smaller fix."
                        ),
                    }
                )
                continue

            if config.dry_run:
                output("[dry run] The approved changes were not written.")
                return AgentOutcome(
                    "dry_run",
                    attempt,
                    "Dry run: the approved changes were not written.",
                    [],
                    last_test,
                )

            # 6. Write the approved files, then run the tests.
            written = apply_changes(workspace, changes)
            changed_files.extend(path for path in written if path not in changed_files)
            output(f"Wrote: {', '.join(written)}")

            last_test = run_tests(workspace, config.test_command, config.test_timeout)
            output(last_test.summary())

            if last_test.passed:
                return AgentOutcome(
                    "fixed",
                    attempt,
                    action.summary or "The tests pass.",
                    changed_files,
                    last_test,
                )

            # 7. The tests failed: send the output back to the model, and start a
            #    new attempt so it can investigate again with that knowledge.
            messages.append({"role": "user", "content": last_test.as_message_for_model()})
            fix_applied = True
            break

        if not fix_applied and attempt < config.max_attempts:
            # All the investigation steps were used up without proposing an edit.
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You used all of your steps for this attempt without proposing an "
                        "edit. Investigate more efficiently and propose a concrete fix."
                    ),
                }
            )

    return AgentOutcome(
        "gave_up",
        config.max_attempts,
        "The tests still failed after the maximum number of attempts.",
        changed_files,
        last_test,
    )
