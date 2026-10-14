"""Shared fixtures for the agent's own test suite.

The tests never touch the network. The model is replaced by the mock provider —
a scripted list of replies — so the *real* agent loop, the real tools, the real
diff and the real pytest are all exercised offline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make the project importable no matter where pytest is invoked from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.config import load_config  # noqa: E402


@pytest.fixture
def make_config(tmp_path):
    """Return a factory that builds a Config pointed at a temporary workspace."""

    def _make(workspace: Path | None = None, **overrides):
        settings = {
            "workspace": Path(workspace or tmp_path),
            "provider": "mock",
            "model": "mock-model",
            "api_key": None,
            "base_url": "http://localhost/unused",
            "test_command": "python -m pytest -q",
            "max_attempts": 3,
            "max_tool_calls": 8,
            "test_timeout": 120.0,
            "auto_approve": False,
            "dry_run": False,
            "mock_responses_file": None,
        }
        settings.update(overrides)
        return load_config(**settings)

    return _make


@pytest.fixture
def write_mock_script(tmp_path):
    """Return a helper that writes a mock reply list and returns its path."""

    def _write(replies: list, name: str = "mock_responses.json") -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(replies, indent=2), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def buggy_workspace(tmp_path):
    """A miniature project with one bug and a pytest suite that detects it."""
    project = tmp_path / "mini_project"
    project.mkdir()

    (project / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    (project / "calc.py").write_text(
        '"""Tiny calculator module with an intentional bug."""\n'
        "\n"
        "\n"
        "def add(a, b):\n"
        "    return a - b\n"
        "\n"
        "\n"
        "def double(value):\n"
        "    return add(value, value)\n",
        encoding="utf-8",
    )

    tests_dir = project / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_calc.py").write_text(
        "from calc import add, double\n"
        "\n"
        "\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
        "\n"
        "\n"
        "def test_double():\n"
        "    assert double(4) == 8\n",
        encoding="utf-8",
    )

    return project
