"""Run the project's test suite and give the output back to the model.

Two rules are enforced here:

* The command comes from *your* configuration (``TEST_COMMAND``). The model can
  never choose, suggest or change it — it has no way to run a command at all.
* Even your command is validated first: it is split into arguments with
  ``shlex`` and never handed to a shell, the executable must be on an allow-list,
  and shell characters such as ``;``, ``&&``, ``|``, ``>`` and ``$(`` are refused.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass

from .workspace import Workspace

# The command must start with one of these. Extend the list if your project uses
# a different test runner.
ALLOWED_EXECUTABLES = frozenset({"python", "python3", "py", "pytest", "py.test", "uv", "tox"})

# These names are replaced by the interpreter running the agent, so the tests
# always run in the same environment (with the same packages installed) as the
# agent itself.
PYTHON_NAMES = frozenset({"python", "python3", "py"})

# Commands are run without a shell, so shell syntax would be passed through
# literally. Refusing it is clearer than a confusing "file not found" error.
SHELL_CHARACTERS = (";", "&&", "||", "|", ">", "<", "`", "$(")

# Only this much output is kept. Long output is cut in the middle, because the
# interesting part of a test failure is at the end.
MAX_OUTPUT_CHARS = 8000


class TestRunnerError(Exception):
    """Raised when the configured test command is missing or unsafe."""


@dataclass
class TestResult:
    """What happened when the tests ran."""

    command: str
    exit_code: int
    output: str
    duration: float
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def summary(self) -> str:
        """One line for the human watching the run."""
        if self.timed_out:
            status = f"TIMED OUT after {self.duration:.1f}s"
        elif self.passed:
            status = f"PASSED in {self.duration:.1f}s"
        else:
            status = f"FAILED (exit code {self.exit_code}) in {self.duration:.1f}s"
        return f"`{self.command}` -> {status}"

    def as_message_for_model(self) -> str:
        """The message sent back to the model after a run, including the output.

        This is what makes the retry work: the failure text goes back into the
        conversation, so the model can see exactly why its fix was not enough.
        """
        if self.timed_out:
            header = f"The test command `{self.command}` timed out after {self.duration:.1f}s."
        elif self.passed:
            header = f"The test command `{self.command}` finished. All tests passed."
        else:
            header = f"The test command `{self.command}` finished. Tests did NOT pass."
        return f"{header}\n\n```\n{self.output.strip() or '(no output)'}\n```"


def validate_command(command: str) -> list[str]:
    """Split the configured command and check that it is safe to run.

    Returns the argument list that will be executed (always with ``shell=False``).
    """
    if not command or not command.strip():
        raise TestRunnerError("No test command configured. Set TEST_COMMAND.")

    try:
        argv = shlex.split(command, posix=os.name != "nt")
    except ValueError as exc:
        raise TestRunnerError(f"Could not parse TEST_COMMAND {command!r}: {exc}") from exc
    if not argv:
        raise TestRunnerError(f"TEST_COMMAND {command!r} is empty.")

    # On Windows shlex keeps surrounding quotes, so a quoted path such as
    # "C:\Python312\python.exe" would fail the allow-list check.
    argv = [_strip_quotes(token) for token in argv]

    for token in argv:
        if any(character in token for character in SHELL_CHARACTERS):
            raise TestRunnerError(
                f"TEST_COMMAND contains a shell character ({token!r}). Commands are run "
                "without a shell, so shell syntax is not supported here."
            )

    if _executable_name(argv[0]) not in ALLOWED_EXECUTABLES:
        raise TestRunnerError(
            f"{argv[0]!r} is not an allowed test executable. "
            f"Allowed: {sorted(ALLOWED_EXECUTABLES)}."
        )
    return argv


def _strip_quotes(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        return token[1:-1]
    return token


def _executable_name(argv0: str) -> str:
    """Normalise an executable name, so ``python.exe`` counts as ``python``."""
    name = os.path.basename(argv0).lower()
    return name[:-4] if name.endswith(".exe") else name


def resolve_interpreter(argv: list[str]) -> list[str]:
    """Point a bare ``python`` at the interpreter that is running the agent.

    Without this, ``python -m pytest`` would pick up whichever ``python`` comes
    first on PATH — often a different environment where pytest, or the project
    itself, is not installed.
    """
    if argv and _executable_name(argv[0]) in PYTHON_NAMES:
        return [sys.executable, *argv[1:]]
    return argv


def run_tests(workspace: Workspace, command: str, timeout: float = 300.0) -> TestResult:
    """Run the configured test command inside the workspace and capture its output."""
    argv = resolve_interpreter(validate_command(command))

    # A clean environment for the child process: import the project from the
    # workspace root, and keep the test run from leaving .pyc files behind.
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(workspace.root), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=str(workspace.root),  # run inside the sandbox, not the repo root
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
            shell=False,  # never a shell
        )
    except subprocess.TimeoutExpired as exc:
        partial = _as_text(exc.stdout) + _as_text(exc.stderr)
        return TestResult(
            command=command,
            exit_code=-1,
            output=_shorten(partial) + f"\n[timed out after {timeout:.0f}s]",
            duration=time.monotonic() - started,
            timed_out=True,
        )
    except FileNotFoundError as exc:
        raise TestRunnerError(
            f"Could not run {argv[0]!r}. Is it installed and on your PATH? ({exc})"
        ) from exc

    return TestResult(
        command=command,
        exit_code=completed.returncode,
        output=_shorten((completed.stdout or "") + (completed.stderr or "")),
        duration=time.monotonic() - started,
    )


def _as_text(value) -> str:
    """subprocess returns bytes when output was cut off mid-line; normalise it."""
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


def _shorten(text: str) -> str:
    """Keep the start and the end of long output, dropping the middle."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    head = MAX_OUTPUT_CHARS // 3
    tail = MAX_OUTPUT_CHARS - head
    return f"{text[:head]}\n... [{len(text) - MAX_OUTPUT_CHARS} characters omitted] ...\n{text[-tail:]}"
