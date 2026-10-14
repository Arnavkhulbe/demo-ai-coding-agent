"""Human approval: the step that stops the agent changing files on its own.

Nothing is written to disk until you have seen the diff and answered "y". This
module only asks the question — the writing happens in ``agent/patch.py``, and
only after this function returns ``True``.
"""

from __future__ import annotations

from typing import Callable

from .patch import FileChange, format_plan


class ApprovalAborted(Exception):
    """Raised when the human stops the whole run at the approval prompt."""


def ask_for_approval(
    changes: list[FileChange],
    *,
    auto_approve: bool = False,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> bool:
    """Show every diff, then return True only if the human says yes.

    ``input_fn`` and ``output_fn`` exist so tests can answer the prompt for you.
    """
    if not changes:
        raise ValueError("There are no changes to approve.")

    output_fn("=" * 72)
    output_fn(f"PROPOSED CHANGES ({len(changes)} file(s))")
    output_fn("=" * 72)
    output_fn(format_plan(changes))
    output_fn("=" * 72)

    if auto_approve:
        output_fn("Auto-approve is enabled; applying the changes.")
        return True

    while True:
        try:
            answer = input_fn("Apply these changes? [y]es / [n]o / [q]uit: ")
        except EOFError:
            # No terminal attached (piped input, or CI). Never guess "yes".
            raise ApprovalAborted(
                "Nobody answered the approval prompt, so no files were modified. "
                "Re-run with --yes if you want changes applied automatically."
            ) from None

        answer = answer.strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no", ""}:
            output_fn("Changes rejected; no files were modified.")
            return False
        if answer in {"q", "quit"}:
            raise ApprovalAborted("Stopped by the user at the approval prompt.")
        output_fn("Please answer 'y', 'n' or 'q'.")
