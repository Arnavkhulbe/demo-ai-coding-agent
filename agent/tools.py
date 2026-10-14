"""The three read-only tools the model may use to explore the code.

They are the agent's eyes. Instead of sending a whole codebase to the LLM, the
model searches for a keyword and then reads only the lines around the match.
That is what keeps the conversation small and cheap.

Every function takes the sandboxed ``Workspace`` first, so no tool can reach
outside the project directory, and every function returns a plain string — that
string is added to the conversation as the tool's result and is also printed for
the human watching the run.
"""

from __future__ import annotations

import re

from .workspace import Workspace, WorkspaceError

# Caps that keep one tool result from filling up the model's context window.
MAX_SEARCH_RESULTS = 50  # most matches one search may return
MAX_READ_LINES = 300  # most lines one read may return
MAX_LIST_ENTRIES = 200  # most files one listing may return


def list_files(workspace: Workspace, path: str = ".") -> str:
    """List the files under ``path`` with their sizes.

    Useful when the model does not know where to start looking.
    """
    files = list(workspace.iter_files(path))
    if not files:
        return f"(no files found under {path!r})"

    lines = [
        f"{workspace.relative(file)}  ({file.stat().st_size} bytes)"
        for file in files[:MAX_LIST_ENTRIES]
    ]
    if len(files) > MAX_LIST_ENTRIES:
        lines.append(f"... and {len(files) - MAX_LIST_ENTRIES} more files")
    return "\n".join(lines)


def search_code(
    workspace: Workspace,
    query: str,
    path: str = ".",
    case_sensitive: bool = False,
) -> str:
    """Find ``query`` in every text file and return ``path:line: text`` rows.

    This is the best first step for the model, because it narrows a whole
    codebase down to a handful of relevant lines.
    """
    if not query or not query.strip():
        raise ValueError("search_code needs a non-empty 'query'.")

    pattern = _compile_search(query, case_sensitive)
    found: list[str] = []

    for file in workspace.iter_files(path):
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # a binary or unreadable file simply cannot be searched
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                found.append(f"{workspace.relative(file)}:{number}: {line.strip()}")
                if len(found) >= MAX_SEARCH_RESULTS:
                    found.append(
                        f"... stopped after {MAX_SEARCH_RESULTS} matches; "
                        "narrow the query if you need more."
                    )
                    return "\n".join(found)

    if not found:
        return f"No matches for {query!r} under {path!r}."
    return "\n".join(found)


def read_file(
    workspace: Workspace,
    path: str,
    start: int = 1,
    end: int | None = None,
) -> str:
    """Read lines ``start`` to ``end`` of a file, with 1-based line numbers.

    The model uses ``start``/``end`` to read only the region around a match
    instead of a whole file.
    """
    start = max(1, int(start))
    end = int(end) if end is not None else start + MAX_READ_LINES - 1
    if end < start:
        raise ValueError(f"read_file: 'end' ({end}) must be >= 'start' ({start}).")
    end = min(end, start + MAX_READ_LINES - 1)

    lines = workspace.read_text(path).splitlines()
    if not lines:
        return f"{path} is empty."

    chunk = lines[start - 1 : end]
    if not chunk:
        return f"{path}: no lines in range {start}-{end} (the file has {len(lines)} lines)."

    last = start + len(chunk) - 1
    width = len(str(last))
    body = "\n".join(
        f"{number:>{width}} | {line}" for number, line in enumerate(chunk, start=start)
    )
    return f"{path} (lines {start}-{last} of {len(lines)})\n{body}"


def _compile_search(query: str, case_sensitive: bool):
    """Compile the query as a regex, falling back to a literal search.

    The fallback means a plain keyword search like ``apply_discount(`` works
    even though ``(`` is a special character in a regular expression.
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        return re.compile(query, flags)
    except re.error:
        return re.compile(re.escape(query), flags)


# The tools the model is allowed to call, looked up by name.
TOOLS = {
    "list_files": list_files,
    "search_code": search_code,
    "read_file": read_file,
}


def run_tool(workspace: Workspace, name: str, args: dict) -> str:
    """Run one tool call.

    An unknown tool name or a bad argument raises ``ValueError``. The agent
    catches that and sends the message back to the model as a tool result, so
    the model can correct itself instead of the run crashing.
    """
    if not isinstance(args, dict):
        raise ValueError(
            f"Tool arguments must be an object of arguments, got {type(args).__name__}."
        )
    if name not in TOOLS:
        raise ValueError(f"Unknown tool {name!r}. Available tools: {sorted(TOOLS)}.")

    try:
        return TOOLS[name](workspace, **args)
    except TypeError as exc:
        # Typically the model invented an argument the tool does not accept.
        raise ValueError(f"Tool {name!r} does not accept those arguments: {exc}") from exc
    except WorkspaceError as exc:
        # e.g. the model asked for a path outside the workspace. Report it as one
        # clear kind of error (ValueError) whichever way the tool failed.
        raise ValueError(str(exc)) from exc
