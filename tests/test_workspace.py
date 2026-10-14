"""Tests for the filesystem sandbox."""

from __future__ import annotations

import pytest

from agent.workspace import Workspace, WorkspaceError


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    return Workspace(tmp_path)


def test_resolve_keeps_paths_inside_the_workspace(workspace):
    assert workspace.resolve("pkg/mod.py") == workspace.root / "pkg" / "mod.py"


def test_root_itself_is_allowed(workspace):
    assert workspace.resolve(".") == workspace.root


def test_parent_traversal_is_rejected(workspace):
    with pytest.raises(WorkspaceError, match="outside the workspace"):
        workspace.resolve("../secrets.txt")


def test_deep_parent_traversal_is_rejected(workspace):
    with pytest.raises(WorkspaceError):
        workspace.resolve("pkg/../../outside.py")


def test_absolute_path_outside_the_workspace_is_rejected(workspace, tmp_path):
    outside = tmp_path.parent / "elsewhere.py"
    with pytest.raises(WorkspaceError):
        workspace.resolve(str(outside))


def test_empty_path_is_rejected(workspace):
    with pytest.raises(WorkspaceError, match="path is required"):
        workspace.resolve("")


def test_read_and_write_round_trip(workspace):
    workspace.write_text("pkg/new.py", "value = 42\n")
    assert workspace.read_text("pkg/new.py") == "value = 42\n"


def test_writing_outside_the_workspace_is_rejected(workspace):
    with pytest.raises(WorkspaceError):
        workspace.write_text("../escape.py", "nope\n")


def test_reading_a_missing_file_raises(workspace):
    with pytest.raises(WorkspaceError, match="File not found"):
        workspace.read_text("pkg/missing.py")


def test_missing_workspace_directory_raises(tmp_path):
    with pytest.raises(WorkspaceError, match="does not exist"):
        Workspace(tmp_path / "nope")


def test_iter_files_skips_cache_directories(workspace):
    cache = workspace.root / "__pycache__"
    cache.mkdir()
    (cache / "junk.pyc").write_text("binary-ish", encoding="utf-8")

    found = {workspace.relative(path) for path in workspace.iter_files(".")}
    assert "pkg/mod.py" in found
    assert "README.md" in found
    assert all("__pycache__" not in name for name in found)


def test_relative_returns_posix_style_paths(workspace):
    assert workspace.relative(workspace.root / "pkg" / "mod.py") == "pkg/mod.py"
