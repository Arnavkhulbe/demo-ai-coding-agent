"""The conversation protocol: the system prompt, and the reply format.

Rather than depending on a provider-specific "function calling" feature, the
agent asks the model for a single JSON object per turn. That works the same way
on OpenAI, OpenRouter, Groq, Ollama and anything else, and it makes the agent
loop easy to read and easy to test.

Every reply must be one of::

    {"thought": "...", "tool": "search_code", "args": {"query": "foo"}}
    {"thought": "...", "action": "propose_fix", "summary": "...", "edits": [...]}
    {"thought": "...", "action": "done", "message": "..."}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .patch import Edit, PatchError, parse_edits

# The three kinds of action a reply can carry.
TOOL_ACTION = "tool"
PROPOSE_FIX = "propose_fix"
DONE = "done"


class ProtocolError(Exception):
    """Raised when the model's reply is not a valid action."""


@dataclass
class Action:
    """One parsed, validated model reply."""

    kind: str  # "tool" | "propose_fix" | "done"
    thought: str = ""
    tool: str = ""
    args: dict = field(default_factory=dict)
    summary: str = ""
    edits: list[Edit] = field(default_factory=list)
    message: str = ""


# ---------------------------------------------------------------------------
# The prompt: what the model is told about its job, its tools and the format
# ---------------------------------------------------------------------------

def build_system_prompt(workspace_display: str, test_command: str) -> str:
    """Describe the agent's role, the tools it may call and the reply format."""
    return f"""You are a careful coding agent that fixes bugs in a real codebase.

WORKSPACE
You may only read and write files inside: {workspace_display}
Use paths relative to the workspace root, for example "shop/pricing.py".
Anything outside that folder is blocked.

HOW YOU WORK
You are never shown the whole codebase. You explore it with the tools below,
decide on the smallest correct change, and propose it. A human reviews your diff
and approves it before anything is written. Then the test suite runs and you are
shown the result. If the tests still fail, you may investigate again and propose
another fix.

TOOLS
- "list_files": list the files under a path. args: {{"path": "."}}
- "search_code": find a keyword in every file, returns "path:line: text" rows.
  args: {{"query": "apply_discount", "path": ".", "case_sensitive": false}}
- "read_file": read a range of lines with line numbers. Read before you edit.
  args: {{"path": "shop/pricing.py", "start": 1, "end": 40}}

REPLY FORMAT
Reply with exactly ONE JSON object and nothing else. Never explain it in prose
and never return several objects.

To use a tool:
  {{"thought": "why you are doing this", "tool": "search_code", "args": {{"query": "apply_discount"}}}}

To propose your fix (this is what triggers the human approval step):
  {{"thought": "...", "action": "propose_fix", "summary": "one-line explanation",
    "edits": [{{"path": "shop/pricing.py", "old": "exact text from the file",
                "new": "replacement text"}}]}}

To stop (the task is already done, or you are stuck):
  {{"thought": "...", "action": "done", "message": "what you found or why you stopped"}}

RULES FOR EDITS
- Read a file with read_file before editing it.
- "old" must be copied from the file VERBATIM, character for character, including
  the indentation. It must appear exactly once unless you set "replace_all": true.
- Keep the change small and targeted. Do not refactor unrelated code.
- Do not modify the test files: they describe the behaviour that is expected.
- You cannot run shell commands. The test command "{test_command}" is chosen by
  the user and is only run for you after your fix is approved.
- If a tool reports an error, read the message and adjust your next action.
"""


# ---------------------------------------------------------------------------
# Parsing the model's reply
# ---------------------------------------------------------------------------

def extract_json_object(text: str) -> dict:
    """Pull the JSON object out of a model reply.

    Models often wrap their JSON in ``` fences or add a sentence around it, so we
    first try the whole reply and then fall back to the text from the first "{"
    to the last "}". If the reply is still unusable we raise, and the agent loop
    simply tells the model what went wrong so it can answer again.
    """
    if not isinstance(text, str) or not text.strip():
        raise ProtocolError("The model returned an empty reply.")

    cleaned = text.strip().replace("```json", "").replace("```", "").strip()

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        # Not pure JSON: try just the outermost {...} part of the reply.
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end < start:
            raise ProtocolError(
                f"The model's reply contains no JSON object: {text[:200]!r}"
            ) from None
        try:
            payload = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"Could not parse the model's JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ProtocolError("The model's reply must be a JSON object.")
    return payload


def parse_action(reply: str) -> Action:
    """Turn one raw model reply into an :class:`Action`.

    Anything unexpected raises :class:`ProtocolError`; the agent sends that
    message back to the model so it can correct itself.
    """
    payload = extract_json_object(reply)
    thought = str(payload.get("thought") or "")

    action = payload.get("action")
    if action is None and "tool" in payload:
        action = TOOL_ACTION  # most replies just name a tool and nothing else
    if not isinstance(action, str) or not action.strip():
        raise ProtocolError(
            'The reply must contain either "tool" or "action". '
            'Example: {"thought": "...", "tool": "search_code", "args": {"query": "foo"}}'
        )
    action = action.strip().lower()

    if action == TOOL_ACTION:
        tool = payload.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            raise ProtocolError('A tool call needs a "tool" field, e.g. "search_code".')
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            raise ProtocolError('"args" must be a JSON object.')
        return Action(kind=TOOL_ACTION, thought=thought, tool=tool.strip(), args=args)

    if action == PROPOSE_FIX:
        try:
            edits = parse_edits(payload.get("edits"))
        except PatchError as exc:
            raise ProtocolError(str(exc)) from exc
        return Action(
            kind=PROPOSE_FIX,
            thought=thought,
            summary=str(payload.get("summary") or ""),
            edits=edits,
        )

    if action == DONE:
        return Action(kind=DONE, thought=thought, message=str(payload.get("message") or ""))

    raise ProtocolError(
        f"Unknown action {action!r}. Use 'tool' with a tool name, 'propose_fix', or 'done'."
    )
