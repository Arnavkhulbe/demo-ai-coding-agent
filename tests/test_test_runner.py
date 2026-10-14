"""Tests for the validated test runner.

These tests prove the second safety requirement: only a validated, user-chosen
command is ever executed, and never through a shell.
"""

from __future__ import annotations

import sys

import pytest

from agent.test_runner import (
    TestRunnerError,
    resolve_interpreter,
    run_tests,
    validate_command,
)
from agent.workspace import Workspace


@pytest.fixture
def workspace(tmp_path):
    return Workspace(tmp_path)


# -- validate_command --------------------------------------------------------

def test_accepts_a_normal_pytest_command():
    assert validate_command("python -m pytest -q") == ["python", "-m", "pytest", "-q"]


def test_accepts_a_bare_pytest_command():
    assert validate_command("pytest tests") == ["pytest", "tests"]


def test_accepts_a_windows_style_executable_name():
    assert validate_command("python.exe -m pytest") == ["python.exe", "-m", "pytest"]


def test_rejects_an_empty_command():
    with pytest.raises(TestRunnerError, match="No test command"):
        validate_command("   ")


def test_rejects_a_non_allowlisted_executable():
    with pytest.raises(TestRunnerError, match="not an allowed test executable"):
        validate_command("rm -rf /")


def test_rejects_a_shell_chain():
    with pytest.raises(TestRunnerError, match="shell character"):
        validate_command("python -m pytest && rm -rf /")


def test_rejects_output_redirection():
    with pytest.raises(TestRunnerError, match="shell character"):
        validate_command("python -m pytest > results.txt")


def test_rejects_command_substitution():
    with pytest.raises(TestRunnerError, match="shell character"):
        validate_command("python -m pytest $(whoami)")


def test_rejects_an_unparseable_command():
    with pytest.raises(TestRunnerError, match="Could not parse"):
        validate_command('python -m pytest "')


def test_strips_quotes_from_a_quoted_executable_path():
    assert validate_command('"python" -m pytest') == ["python", "-m", "pytest"]


def test_bare_python_is_resolved_to_the_running_interpreter():
    assert resolve_interpreter(["python", "-m", "pytest", "-q"]) == [
        sys.executable,
        "-m",
        "pytest",
        "-q",
    ]


def test_pytest_is_not_rewritten_to_the_running_interpreter():
    assert resolve_interpreter(["pytest", "tests"]) == ["pytest", "tests"]


# -- TestRunner.run ----------------------------------------------------------

def _write_script(workspace: Workspace, name: str, body: str) -> None:
    workspace.write_text(name, body)


def test_run_reports_success_for_a_passing_command(workspace):
    _write_script(workspace, "ok.py", "print('all good')\n")
    result = run_tests(workspace, "python ok.py")

    assert result.passed
    assert result.exit_code == 0
    assert "all good" in result.output
    assert "PASSED" in result.summary()
    assert "All tests passed" in result.as_message_for_model()


def test_run_reports_failure_for_a_failing_command(workspace):
    _write_script(workspace, "bad.py", "print('boom')\nraise SystemExit(3)\n")
    result = run_tests(workspace, "python bad.py")

    assert not result.passed
    assert result.exit_code == 3
    assert "boom" in result.output
    assert "FAILED" in result.summary()
    assert "did NOT pass" in result.as_message_for_model()


def test_run_uses_the_workspace_as_working_directory(workspace):
    _write_script(workspace, "cwd_check.py", "import os\nprint(os.getcwd())\n")
    result = run_tests(workspace, "python cwd_check.py")
    assert str(workspace.root) in result.output


def test_run_makes_the_workspace_importable(workspace):
    _write_script(workspace, "importable.py", "import helper\nprint(helper.VALUE)\n")
    _write_script(workspace, "helper.py", "VALUE = 'hello from helper'\n")
    result = run_tests(workspace, "python importable.py")
    assert result.passed
    assert "hello from helper" in result.output


def test_run_times_out_instead_of_hanging_forever(workspace):
    _write_script(workspace, "slow.py", "import time\ntime.sleep(30)\n")
    result = run_tests(workspace, "python slow.py", timeout=0.6)

    assert not result.passed
    assert result.timed_out
    assert "TIMED OUT" in result.summary()


def test_validate_uses_the_current_interpreter_when_asked(workspace):
    # Sanity check that our tests exercise a real interpreter.
    assert sys.executable
    _write_script(workspace, "exit0.py", "raise SystemExit(0)\n")
    assert run_tests(workspace, "python exit0.py").passed
