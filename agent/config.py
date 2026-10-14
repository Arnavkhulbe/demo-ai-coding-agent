"""All of the agent's settings, read from environment variables.

Nothing here touches the network or your project's files. This module only turns
environment variables (and an optional ``.env`` file) into one ``Config`` object
that every other module reads. Keeping every setting in one place means you can
change how the agent behaves without editing any code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# The repository root = the folder that contains the ``agent`` package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TEST_COMMAND = "python -m pytest -q"
DEFAULT_MOCK_RESPONSES = PROJECT_ROOT / "examples" / "mock_responses.json"

# Values that count as "on" for a true/false setting.
TRUE_VALUES = {"1", "true", "yes", "on"}


def load_dotenv(path: Path | None = None) -> None:
    """Copy ``KEY=VALUE`` lines from a .env file into ``os.environ``.

    Real environment variables always win, so exporting a variable in your shell
    overrides whatever the file says. This is a tiny replacement for the
    third-party ``python-dotenv`` package, which keeps the agent dependency-free.
    """
    path = path or (PROJECT_ROOT / ".env")
    if not path.is_file():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def setting(name: str, default: str) -> str:
    """Read one setting as text (falling back to ``default`` when it is unset)."""
    value = os.environ.get(name, "").strip()
    return value or default


def setting_number(name: str, default: float) -> float:
    """Read one setting as a number, e.g. 60 or 0.5."""
    value = setting(name, str(default))
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {value!r}") from None


def setting_int(name: str, default: int) -> int:
    """Read one setting as a whole number, e.g. 3."""
    return int(setting_number(name, default))


def setting_bool(name: str, default: bool = False) -> bool:
    """Read one setting as an on/off switch ("1", "true", "yes" or "on")."""
    return setting(name, "1" if default else "0").lower() in TRUE_VALUES


def resolve_path(value: str) -> Path:
    """Turn a possibly-relative path into an absolute one.

    Relative paths are read from the repository root, so the agent behaves the
    same way no matter which folder you start it from.
    """
    path = Path(value).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


@dataclass
class Config:
    """Every setting the agent uses, in one place.

    Build one with :func:`load_config`; never edit the fields while a run is in
    progress, because the whole loop reads from this object.
    """

    # Where the agent is allowed to read and write files.
    workspace: Path
    # The command that runs the project's tests. It comes from *you*, never
    # from the model.
    test_command: str

    # How to reach the model.
    provider: str
    model: str
    api_key: str | None
    base_url: str
    temperature: float
    llm_timeout: float

    # How hard the agent tries, and for how long.
    max_attempts: int
    max_tool_calls: int
    test_timeout: float

    # Safety switches.
    auto_approve: bool
    dry_run: bool
    mock_responses_file: Path | None

    def describe_llm(self) -> str:
        """A one-line description of the model, safe to print (no API key)."""
        if self.provider == "mock":
            return f"mock ({self.mock_responses_file})"
        return f"{self.provider} / {self.model} @ {self.base_url}"


def load_config(**overrides) -> Config:
    """Build a :class:`Config` from the environment, then apply ``overrides``.

    The CLI passes its command-line flags in as overrides, so this is the single
    place where settings are decided. Anything not named in ``overrides`` is
    read from the environment.
    """
    load_dotenv()

    settings = {
        "workspace": resolve_path(setting("WORKSPACE", "./sample_project")),
        "test_command": setting("TEST_COMMAND", DEFAULT_TEST_COMMAND),
        "provider": setting("LLM_PROVIDER", "openai").lower(),
        "model": setting("LLM_MODEL", "gpt-4o-mini"),
        "api_key": os.environ.get("LLM_API_KEY") or None,
        "base_url": setting("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "temperature": setting_number("LLM_TEMPERATURE", 0.0),
        "llm_timeout": setting_number("LLM_TIMEOUT", 60.0),
        "max_attempts": setting_int("MAX_ATTEMPTS", 3),
        "max_tool_calls": setting_int("MAX_TOOL_CALLS", 10),
        "test_timeout": setting_number("TEST_TIMEOUT", 300.0),
        "auto_approve": setting_bool("AGENT_AUTO_APPROVE"),
        "dry_run": setting_bool("AGENT_DRY_RUN"),
        "mock_responses_file": resolve_path(
            setting("MOCK_RESPONSES_FILE", str(DEFAULT_MOCK_RESPONSES))
        ),
    }
    settings.update(overrides)
    return Config(**settings)
