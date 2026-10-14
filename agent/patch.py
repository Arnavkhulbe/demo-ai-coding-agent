"""Turning a proposed edit into a diff you can review, and then applying it.

The model never writes files. It proposes *edits*: a path, the exact existing
text to replace, and the replacement text. That is what keeps a fix targeted —
the model cannot rewrite a whole file, it can only replace text it has quoted.

1. check the proposed edits are well formed (:func:`parse_edits`),
2. work out the new file contents and a unified diff (:func:`plan_changes`) —
   this is what you review, and nothing has been written yet,
3. write the files (:func:`apply_changes`), only after you approve.

Because the diff and the written bytes come from the same in-memory plan, what
you approved is exactly what ends up on disk.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from .workspace import Workspace, WorkspaceError


class PatchError(Exception):
    """Raised when a proposed edit is malformed, or cannot be applied."""


@dataclass(frozen=True)
class Edit:
    """One search-and-replace operation proposed by the model.

    ``old`` must be copied verbatim from the file, and must not be empty: there
    is no way for the model to write a file from scratch.
    """

    path: str
    old: str
    new: str
    replace_all: bool = False


@dataclass
class FileChange:
    """A file's contents before and after the edits, plus the diff between them."""

    path: str
    original: str
    updated: str
    diff: str


def parse_edits(raw_edits) -> list[Edit]:
    """Validate the ``edits`` field of a ``propose_fix`` reply."""
    if not isinstance(raw_edits, list) or not raw_edits:
        raise PatchError(
            "'edits' must be a non-empty list of objects like "
            '{"path": "a.py", "old": "...", "new": "..."}.'
        )

    edits: list[Edit] = []
    for index, raw in enumerate(raw_edits):
        if not isinstance(raw, dict):
            raise PatchError(f"edits[{index}] must be an object, got {type(raw).__name__}.")

        path = raw.get("path")
        if not isinstance(path, str) or not path.strip():
            raise PatchError(f"edits[{index}] is missing a non-empty string 'path'.")

        old = raw.get("old")
        if not isinstance(old, str) or old == "":
            raise PatchError(
                f"edits[{index}] needs a non-empty 'old': the exact existing text to replace."
            )

        if not isinstance(raw.get("new"), str):
            raise PatchError(f"edits[{index}] needs a 'new' string: the replacement text.")

        if old == raw["new"]:
            raise PatchError(f"edits[{index}] does not change anything ('old' equals 'new').")

        replace_all = raw.get("replace_all", False)
        if not isinstance(replace_all, bool):
            raise PatchError(f"edits[{index}]['replace_all'] must be true or false.")

        edits.append(
            Edit(
                path=path.strip().replace("\\", "/"),
                old=old,
                new=raw["new"],
                replace_all=replace_all,
            )
        )
    return edits


def plan_changes(workspace: Workspace, edits: list[Edit]) -> list[FileChange]:
    """Work out what every edited file would look like. Nothing is written here.

    Raises :class:`PatchError` if the ``old`` text is not in the file or appears
    more than once, so the model can be asked to read the file again instead of a
    file being quietly corrupted.
    """
    changes: list[FileChange] = []

    for path in _edited_paths(edits):
        try:
            original = workspace.read_text(path)
        except WorkspaceError as exc:
            raise PatchError(f"Cannot edit {path!r}: {exc}") from exc

        updated = original
        for edit in [edit for edit in edits if edit.path == path]:
            updated = _apply_edit(edit, updated)

        if updated == original:
            raise PatchError(f"The edits for {path!r} leave the file unchanged.")

        changes.append(
            FileChange(
                path=path,
                original=original,
                updated=updated,
                diff=_unified_diff(path, original, updated),
            )
        )
    return changes


def _edited_paths(edits: list[Edit]) -> list[str]:
    """The edited paths, in the order they first appear."""
    paths: list[str] = []
    for edit in edits:
        if edit.path not in paths:
            paths.append(edit.path)
    return paths


def _apply_edit(edit: Edit, text: str) -> str:
    """Apply one edit to an in-memory string."""
    occurrences = text.count(edit.old)
    if occurrences == 0:
        raise PatchError(
            f"'old' text was not found in {edit.path!r}. Read the file again and copy the "
            "exact text, including the indentation."
        )
    if occurrences > 1 and not edit.replace_all:
        raise PatchError(
            f"'old' text appears {occurrences} times in {edit.path!r}. Include more of the "
            'surrounding lines to make it unique, or set "replace_all": true.'
        )
    return text.replace(edit.old, edit.new, -1 if edit.replace_all else 1)


def _unified_diff(path: str, original: str, updated: str) -> str:
    """Build a unified diff with a few lines of context around each change."""
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )


def format_plan(changes: list[FileChange]) -> str:
    """Render every diff, ready to be shown for approval."""
    return "\n\n".join(f"--- {change.path}\n{change.diff.rstrip()}" for change in changes)


def apply_changes(workspace: Workspace, changes: list[FileChange]) -> list[str]:
    """Write each planned file. Only ever called after the human approves."""
    written: list[str] = []
    for change in changes:
        workspace.write_text(change.path, change.updated)
        written.append(change.path)
    return written
