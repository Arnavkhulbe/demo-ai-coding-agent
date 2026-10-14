"""The LLM service: the only module that talks to a language model.

It has two providers, chosen with the ``LLM_PROVIDER`` setting:

``openai``
    Any OpenAI-compatible ``POST {base_url}/chat/completions`` endpoint. That
    covers OpenAI, OpenRouter, Groq, Together, DeepSeek and local servers such
    as Ollama — switching provider is just a change of ``LLM_BASE_URL`` and
    ``LLM_MODEL``.

``mock``
    Replays a fixed list of replies from a JSON file. It is a stand-in for the
    model, so you can run and test the *whole* agent without an API key, without
    a network connection, and without spending money. It is only for that: it
    makes no decisions of its own.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

# A chat message looks like {"role": "user", "content": "..."}.
Message = dict[str, str]


class LLMError(Exception):
    """Raised when the model could not be reached, or returned something unusable."""


def load_scripted_replies(path: str | Path | None) -> list[str]:
    """Read the mock reply list, as the text a model would have sent.

    A reply may be a plain string (literally what a model returns) or a JSON
    object (easier to read and edit by hand); objects are converted to text.
    """
    if not path:
        raise LLMError(
            "LLM_PROVIDER=mock needs MOCK_RESPONSES_FILE to point at a JSON file "
            "of scripted replies (see examples/mock_responses.json)."
        )

    path = Path(path).expanduser()
    if not path.is_file():
        raise LLMError(f"Mock responses file not found: {path}")

    try:
        script = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LLMError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(script, list):
        raise LLMError(f"{path} must contain a JSON list of replies.")

    replies: list[str] = []
    for index, item in enumerate(script):
        if isinstance(item, str):
            replies.append(item)
        elif isinstance(item, dict):
            replies.append(json.dumps(item))
        else:
            raise LLMError(f"{path}: reply {index} must be a string or an object.")
    return replies


class LLM:
    """Ask the model for its next reply."""

    def __init__(self, config) -> None:
        self.config = config
        self._replies = (
            load_scripted_replies(config.mock_responses_file)
            if config.provider == "mock"
            else []
        )
        self._next_reply = 0

    def complete(self, messages: list[Message]) -> str:
        """Send the conversation so far and return the model's raw text reply."""
        if self.config.provider == "mock":
            return self._replay_scripted_reply()
        if self.config.provider == "openai":
            return self._post_chat_completions(messages)
        raise LLMError(
            f"Unknown LLM_PROVIDER {self.config.provider!r}. "
            "Use 'openai' (any OpenAI-compatible API) or 'mock'."
        )

    # -- the offline provider -------------------------------------------------

    def _replay_scripted_reply(self) -> str:
        """Return the next scripted reply, or fail loudly if the script ran out."""
        if self._next_reply >= len(self._replies):
            raise LLMError(
                "The mock response script ran out: the agent asked for more replies "
                f"than {self.config.mock_responses_file} contains."
            )
        reply = self._replies[self._next_reply]
        self._next_reply += 1
        return reply

    # -- the real API ---------------------------------------------------------

    def _post_chat_completions(self, messages: list[Message]) -> str:
        """Send one request to an OpenAI-compatible chat endpoint."""
        config = self.config
        if not config.api_key:
            raise LLMError(
                "No API key configured. Set LLM_API_KEY in your environment or in a "
                ".env file (copy .env.example to .env to get started)."
            )

        url = f"{config.base_url}/chat/completions"
        body = json.dumps(
            {
                "model": config.model,
                "messages": messages,
                "temperature": config.temperature,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key}",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=config.llm_timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise LLMError(f"HTTP {exc.code} from the LLM API: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"Could not reach the LLM API at {url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMError(
                f"The LLM API at {url} took longer than {config.llm_timeout}s to answer."
            ) from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"The LLM API did not return JSON: {raw[:300]!r}") from exc

        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected reply shape from the LLM API: {payload!r}") from exc
