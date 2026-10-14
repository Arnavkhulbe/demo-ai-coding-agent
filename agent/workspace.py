"""The filesystem sandbox.

Every read and write done on behalf of the model goes through ``Workspace``. It
is the single gate for touching files, so a confused or malicious model reply can
never reach outside the project directory you point the agent at.
"""

from __future__ import annotations

from pathlib import Path

# Folders the agent never walks into: caches, virtualenvs, VCS metadata. They add
# noise to search results and are never the right place for a fix.
IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".freebuff",
        ".idea",
        ".vscode",
        "build",
        "dist",
    }
)

# Files bigger than this are skipped when searching: they are almost never
# hand-written source, and reading one would waste the model's context.
MAX_SEARCHABLE_FILE_BYTES = 1_000_000


class WorkspaceError(Exception):
    """Raised when an operation would escape the workspace, or is otherwise invalid."""


class Workspace:
    """A directory the agent is allowed to read from and write to."""

    def __init__(self, root: str | Path) -> None:
        resolved = Path(root).expanduser().resolve()
        if not resolved.exists():
            raise WorkspaceError(f"Workspace directory does not exist: {resolved}")
        if not resolved.is_dir():
            raise WorkspaceError(f"Workspace path is not a directory: {resolved}")
        self.root = resolved

    def resolve(self, path: str | Path) -> Path:
        """Turn a caller-supplied path into an absolute path inside the workspace.

        Anything that escapes the root raises :class:`WorkspaceError` — including
        ``../`` traversal and absolute paths elsewhere on disk.
        """
        if path is None or str(path).strip() == "":
            raise WorkspaceError("A file path is required.")

        candidate = Path(str(path))
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (self.root / candidate).resolve()

        if resolved != self.root and self.root not in resolved.parents:
            raise WorkspaceError(
                f"Path {path!r} is outside the workspace ({self.root}). "
                "Only files inside the workspace can be accessed."
            )
        return resolved

    def relative(self, path: Path) -> str:
        """Return a workspace-relative path for display, e.g. ``shop/pricing.py``."""
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def iter_files(self, start: str | Path = "."):
        """Yield every searchable file under ``start``, in sorted order."""
        base = self.resolve(start)
        if base.is_file():
            yield base
            return

        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(part in IGNORED_DIRECTORIES for part in path.relative_to(self.root).parts):
                continue
            try:
                if path.stat().st_size > MAX_SEARCHABLE_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield path

    def read_text(self, path: str | Path) -> str:
        """Read a UTF-8 text file from inside the workspace."""
        resolved = self.resolve(path)
        if not resolved.is_file():
            raise WorkspaceError(f"File not found: {self.relative(resolved)}")
        try:
            return resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceError(f"{self.relative(resolved)} is not a UTF-8 text file.") from exc
        except OSError as exc:
            raise WorkspaceError(f"Could not read {self.relative(resolved)}: {exc}") from exc

    def write_text(self, path: str | Path, content: str) -> Path:
        """Write UTF-8 text to a file inside the workspace.

        This is the only write path in the whole codebase, and the agent calls it
        exclusively after the human approved the diff.
        """
        resolved = self.resolve(path)
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8", newline="")
        except OSError as exc:
            raise WorkspaceError(f"Could not write {self.relative(resolved)}: {exc}") from exc
        return resolved
