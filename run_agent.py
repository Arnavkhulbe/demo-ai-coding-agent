#!/usr/bin/env python3
"""Command-line entry point for the AI Coding Agent.

Examples
--------
Let the agent fix the bug in the included sample project::

    python run_agent.py "The pricing tests are failing. Find and fix the bug."

See the diff without writing anything::

    python run_agent.py "Fix the failing tests" --dry-run

Run it fully offline against a scripted model (no API key needed)::

    python run_agent.py --provider mock --yes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent.agent import run_agent
from agent.config import load_config
from agent.llm import LLMError
from agent.test_runner import TestRunnerError
from agent.workspace import WorkspaceError

DEFAULT_TASK = "The project's tests are failing. Find the cause and fix it."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_agent.py",
        description="An LLM-powered coding agent that fixes bugs in an existing codebase.",
    )
    parser.add_argument(
        "task",
        nargs="?",
        help="What you want the agent to do. Omit it to be prompted.",
    )
    parser.add_argument("--workspace", help="Directory the agent may modify (default: $WORKSPACE).")
    parser.add_argument("--test-command", help="Command used to run the tests (default: $TEST_COMMAND).")
    parser.add_argument("--provider", help="LLM provider: 'openai' or 'mock'.")
    parser.add_argument("--model", help="Model name to send to the API.")
    parser.add_argument("--max-attempts", type=int, help="Retry limit for fix -> test cycles.")
    parser.add_argument("--max-steps", type=int, help="Max model steps per attempt.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Approve every proposed diff automatically (non-interactive).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the diff and test plan but never write to disk.",
    )
    return parser


def overrides_from_args(args: argparse.Namespace) -> dict:
    """Turn the flags the user actually passed into config overrides."""
    overrides: dict = {}
    if args.workspace:
        # A path typed on the command line is relative to the current directory.
        overrides["workspace"] = Path(args.workspace).expanduser().resolve()
    if args.test_command:
        overrides["test_command"] = args.test_command
    if args.provider:
        overrides["provider"] = args.provider.lower()
    if args.model:
        overrides["model"] = args.model
    if args.max_attempts is not None:
        overrides["max_attempts"] = max(1, args.max_attempts)
    if args.max_steps is not None:
        overrides["max_tool_calls"] = max(1, args.max_steps)
    if args.yes:
        overrides["auto_approve"] = True
    if args.dry_run:
        overrides["dry_run"] = True
    return overrides


def read_task(task_argument: str | None) -> str | None:
    """Return the task to work on, asking for it when running interactively."""
    if task_argument:
        return task_argument

    if sys.stdin.isatty():
        try:
            return input("Describe the coding task: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

    # Non-interactive (a script or CI): use the default task, so
    # `python run_agent.py --provider mock --yes` works unattended.
    print(f"No task given; using the default: {DEFAULT_TASK}")
    return DEFAULT_TASK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config(**overrides_from_args(args))
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    task = read_task(args.task)
    if not task:
        print("No task given. Nothing to do.", file=sys.stderr)
        return 2

    try:
        outcome = run_agent(task, config)
    except KeyboardInterrupt:
        print("\nInterrupted by the user.", file=sys.stderr)
        return 1
    except (WorkspaceError, LLMError, TestRunnerError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print()
    print("=" * 72)
    print("RESULT")
    print("=" * 72)
    print(f"status  : {outcome.status}")
    print(f"attempts: {outcome.attempts}")
    if outcome.changed_files:
        print(f"changed : {', '.join(outcome.changed_files)}")
    if outcome.test_result:
        print(f"tests   : {outcome.test_result.summary()}")
    if outcome.message:
        print(f"message : {outcome.message}")

    return 0 if outcome.status in {"fixed", "done", "dry_run"} else 1


if __name__ == "__main__":
    sys.exit(main())
