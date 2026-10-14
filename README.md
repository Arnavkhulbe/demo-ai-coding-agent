# AI Coding Agent

A small coding agent in the spirit of Claude Code or Codex, written to be read
line by line. You give it a task in plain English; it searches an existing
codebase, reads the relevant parts, asks an LLM to propose a small edit, shows
you the diff, and only applies it **after you approve** — then runs the tests,
and if they fail it sends the failure back to the model and tries again.

```
task ─▶ search ─▶ read ─▶ LLM proposes an edit ─▶ YOU approve ─▶ apply ─▶ tests
                    ▲                                                         │
                    └─────────── retry (up to MAX_ATTEMPTS) ◀─────────────────┘
```

The whole `agent/` package is about 1,450 lines, and no module is longer than
250 lines. The agent itself is **one function** in one file. There are no
frameworks, no databases, and no third-party runtime dependencies — only
Python's standard library.

---

## 1. Quick start

You need **Python 3.9 or newer** (3.12 recommended).

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate
# Windows (Git Bash)
source .venv/Scripts/activate
# Windows (PowerShell)
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt      # installs pytest, nothing else
```

### Watch it work with no API key (offline demo)

The repository ships with a small buggy project (`sample_project/`) and a
scripted stand-in for the model, so you can watch the whole pipeline run offline
and for free:

```bash
python run_agent.py --provider mock --yes
```

You will see it search the code, read the file, print a diff, approve it, apply
it, and report that the failing tests now pass:

```
--- shop/pricing.py
--- a/shop/pricing.py
+++ b/shop/pricing.py
@@ -20,7 +20,7 @@
     if not 0 <= percent_off <= 100:
         raise ValueError("percent_off must be between 0 and 100")

-    return price - price * percent_off
+    return price - price * (percent_off / 100)

`python -m pytest -q` -> PASSED in 0.6s
```

The demo fixes the sample project's bug, so put it back before running again:

```bash
python reset_sample.py
```

### Run it against a real LLM

```bash
cp .env.example .env
# now edit .env and set LLM_API_KEY (and LLM_MODEL if you like)

python run_agent.py "The pricing tests are failing. Find and fix the bug."
```

By default you see the diff and answer `y`, `n` or `q`. Add `--dry-run` to see
the diff without writing anything, or `--yes` to skip the prompt.

> **Note:** the test suite and the offline demo both use the mock model. The real
> HTTP path has not been exercised against a live API from this machine (no key
> available). See [Limitations](#9-limitations).

---

## 2. Configuration

Everything comes from environment variables. A `.env` file is loaded
automatically, and real environment variables always win over it. See
[.env.example](.env.example) for comments on each one.

| Variable | Default | Meaning |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` | `openai` = any OpenAI-compatible API, `mock` = offline scripted replies |
| `LLM_API_KEY` | – | Your API key (required for `openai`) |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Point this at any compatible endpoint |
| `LLM_MODEL` | `gpt-4o-mini` | Model name that endpoint understands |
| `LLM_TEMPERATURE` | `0` | `0` keeps fixes deterministic |
| `LLM_TIMEOUT` | `60` | Seconds to wait for one reply |
| `WORKSPACE` | `./sample_project` | The **only** folder the agent may touch |
| `TEST_COMMAND` | `python -m pytest -q` | The command used to run the tests |
| `MAX_ATTEMPTS` | `3` | Retry limit for fix → test cycles |
| `MAX_TOOL_CALLS` | `10` | Most model steps within one attempt |
| `TEST_TIMEOUT` | `300` | Seconds one test run may take |
| `AGENT_AUTO_APPROVE` | `0` | `1` skips the approval prompt |
| `MOCK_RESPONSES_FILE` | `./examples/mock_responses.json` | The script used when `LLM_PROVIDER=mock` |

Any of them can be overridden for one run:

```bash
python run_agent.py "Fix the failing tests" --dry-run --workspace ./sample_project
```

Because the agent speaks the plain OpenAI `/chat/completions` wire format,
switching provider is only configuration:

```bash
# A local model through Ollama
LLM_BASE_URL=http://localhost:11434/v1 LLM_API_KEY=ollama LLM_MODEL=qwen2.5-coder \
  python run_agent.py "Fix the failing tests"
```

---

## 3. The files, one at a time

Every module has exactly one job, and only `agent.py` has the control flow. Read
them in this order: `config.py` → `workspace.py` → `llm.py` → `tools.py` →
`patch.py` → `approval.py` → `test_runner.py` → `protocol.py` → `agent.py`.

| File | Lines | Its one job |
| --- | --- | --- |
| `run_agent.py` | 144 | The command-line entry point: read your flags, call `run_agent`, print the result |
| `agent/agent.py` | 241 | **The main loop.** `run_agent(task, config)` — everything else is a detail it calls |
| `agent/config.py` | 146 | All settings, read from environment variables into one `Config` |
| `agent/workspace.py` | 127 | The sandbox: every path must resolve inside the project folder |
| `agent/llm.py` | 154 | Asks the model for its next reply (real API, or the offline mock) |
| `agent/tools.py` | 156 | What the model may **look** at: `list_files`, `search_code`, `read_file` |
| `agent/patch.py` | 178 | Turns proposed edits into a diff, then writes them once approved |
| `agent/approval.py` | 61 | Shows that diff and asks you `y`/`n`/`q` |
| `agent/test_runner.py` | 201 | Validates and runs your test command, and keeps the output |
| `agent/protocol.py` | 180 | The system prompt, and how a model reply is parsed and checked |
| `sample_project/` | – | A tiny buggy project for the agent to fix (the demo target) |
| `tests/` | – | The agent's own test suite (102 tests, no network needed) |
| `examples/mock_responses.json` | – | The "scripted model" used by the offline demo |
| `reset_sample.py` | – | Puts the sample project's bug back |

### The main loop in plain words

`agent/agent.py` is one function, `run_agent`. It does this:

1. Send the prompt (the job, the tools, the reply format) and your task.
2. Loop up to `MAX_TOOL_CALLS` times, asking the model for **one JSON object** each time:
   - `{"tool": "search_code", "args": {...}}` → run that tool, add its result to the
     conversation, ask again. The model may use tools as often as it likes.
   - `{"action": "propose_fix", "edits": [...]}` → leave the loop. `patch.py` checks the
     edits and builds the new file contents plus a diff **in memory**.
   - `{"action": "done", "message": "..."}` → stop.
3. `approval.py` shows you the diff and waits for your answer.
   - **You say no** → the model is told, and may propose something else. This does not
     use up an attempt.
4. `patch.py` writes the approved files.
5. `test_runner.py` runs your test command and prints the result.
   - **Tests pass** → finished, status `fixed`.
   - **Tests fail** → the failure text is added to the conversation and the whole thing
     runs again as the next attempt, up to `MAX_ATTEMPTS`.

That is the entire agent. The steps are numbered in the code with the same
numbers as above, so you can follow one run through the function.

### Why the whole codebase is never sent to the LLM

`tools.py` is what keeps the conversation small, which keeps it cheap and accurate:

* `search_code` walks the project (skipping `.git`, `__pycache__`, `.venv`, …) and
  returns only matching lines as `path:line: text`.
* `read_file` returns a numbered **range** of lines, so the model reads the 30 lines
  around a match instead of a 2,000-line file.
* `list_files` gives the model the layout when it does not know where to start.

Every tool result is capped (50 matches, 300 lines, 200 files) so one call cannot
blow up the model's context window.

---

## 4. How each required feature is implemented

| # | Requirement | Where, and how |
| --- | --- | --- |
| 1 | The LLM receives the task | `agent.py` — the task is the first user message; every step is one `LLM.complete()` call |
| 2 | A tool searches the codebase | `tools.py::search_code` — regex or plain keyword search over the workspace |
| 3 | A tool reads the file | `tools.py::read_file` — reads a line range with line numbers, not whole files |
| 4 | A targeted edit, not a rewrite | `patch.py` — the model may only replace text it quotes from the file; there is no way to write a file wholesale |
| 5 | Human approval before applying | `approval.py::ask_for_approval` — prints the diff and requires `y`; `patch.py::apply_changes` is only called afterwards |
| 6 | Tests run after applying | `test_runner.py::run_tests` — runs your command and captures the output |
| 7 | Failure goes back to the LLM, with a limit | `agent.py` step 7 — the failed test output is appended to the conversation; `MAX_ATTEMPTS` bounds the cycles |

---

## 5. Safety guarantees

These are properties the code enforces, not just things it claims:

| Guarantee | How it is enforced |
| --- | --- |
| **Only the workspace can be touched** | `workspace.py` resolves every path and rejects anything outside the root, including `../` traversal and absolute paths. It is the only module that touches the filesystem. |
| **The LLM cannot run commands** | The model has exactly three read-only tools. The reply parser accepts only `list_files`, `search_code`, `read_file`, `propose_fix` and `done`. |
| **Even your test command is validated** | `test_runner.py` splits it with `shlex`, refuses shell characters (`;`, `&&`, `\|`, `>`, `$(` …), requires the executable to be on an allow-list, and always runs with `shell=False`. |
| **Nothing is written before you approve** | Edits are worked out in memory by `plan_changes()`. `apply_changes()` runs only after approval returns `True`, and writes the very bytes you saw in the diff. |
| **Edits are never guessed** | The `old` text must appear in the file **verbatim**, exactly once. If it does not, the edit is refused and the model is told to read the file again. |
| **It cannot loop forever** | `MAX_TOOL_CALLS` bounds the steps in one attempt, `MAX_ATTEMPTS` bounds the fix → test cycles, and `TEST_TIMEOUT` bounds each test run. |
| **A missing answer is never a "yes"** | If nobody answers the approval prompt (piped input, CI), the run stops with `aborted` instead of guessing. |

---

## 6. The sample project and its intentional bug

`sample_project/` is a miniature shop package, and it is *meant* to fail:

```bash
cd sample_project && python -m pytest -q
# 5 failed, 9 passed
```

`shop/pricing.py::apply_discount` multiplies the price by a **percentage** instead
of a fraction, so a 20% discount subtracts 2000%:

```python
return price - price * percent_off          # the bug
return price - price * (percent_off / 100)  # what it should say
```

The tests in `sample_project/tests/` are the specification: `apply_discount(100.0,
20)` must be `80.0`. The same bug also breaks `shop/orders.py`, which builds on
`pricing.py`, so the agent has to follow the failures back to the shared cause
instead of patching the symptom.

---

## 7. Running the tests

The agent's own suite never touches the network. The model is replaced by the mock
provider, so the *real* loop — real tools, real diffs, real approval, real pytest —
runs end to end.

```bash
python -m pytest -q          # 102 passed
```

| Test file | What it covers |
| --- | --- |
| `tests/test_workspace.py` | Sandbox escapes, read/write round trips, skipping caches |
| `tests/test_tools.py` | Search, line-range reads, unknown tools, bad arguments |
| `tests/test_patch.py` | Edit validation, diffs, ambiguity detection, applying |
| `tests/test_protocol.py` | Pulling JSON out of messy replies, every action type |
| `tests/test_approval.py` | Diff shown before the question, y/n/q, aborts |
| `tests/test_test_runner.py` | Command validation, allow-list, execution, timeouts |
| `tests/test_agent_loop.py` | The whole loop: fix, retry after a failure, rejection, dry-run, give-up |

The sample project has its own `pytest.ini`, so its (intentionally failing) tests
only run when you ask for them:

```bash
cd sample_project && python -m pytest -q
```

---

## 8. How this code was simplified

The project was written, then rewritten twice to be explainable. These are the
things that were removed and what replaced them:

| Removed | Replaced by |
| --- | --- |
| A `CodingAgent` class with a `run()` method and two private helpers | One function, `run_agent(task, config)`, in `agent.py`. The loop is visible from top to bottom |
| An `ApprovalFlow` class held only a config value | A plain function, `ask_for_approval(changes, ...)` |
| An `LLMProvider` base class, two provider classes, a `create_provider()` factory and an `LLMService` wrapper (five classes for one job) | One `LLM` class whose `complete()` either calls the API or replays the mock script |
| Writing a whole file when `old` was empty | Removed entirely. Requirement 4 asks for targeted edits, so the model can only replace text it quotes |
| A `ToolSpec` catalogue describing each tool, plus code that inspected a function's own parameter names to reject bad arguments | A plain `TOOLS = {"search_code": search_code, ...}` dictionary; bad arguments are caught by a short `try/except TypeError` |
| A 40-line character-by-character JSON scanner | Try `json.loads` on the reply, then on the outermost `{...}`. If it still fails, the loop tells the model and it answers again |
| A `TestRunner` class | One function, `run_tests(workspace, command, timeout)` |
| A frozen `Config` with `with_overrides()` and four env helpers (two of them near-duplicates) | One `load_config(**overrides)` function and three small `setting*` helpers |
| Automatic HTTP retries with exponential backoff | A single request with a clear error message. Transient-failure retries are not a required feature and are hard to explain |
| Four `_something_feedback()` methods that built the "tell the model what went wrong" strings | Those strings are written where they are sent, so the cause and the message sit together |
| Truncating and indenting the tool output for the human | Dropped: the tools already cap their own results (50 matches, 300 lines), so this was duplicate logic |
| Dead code: `AgentOutcome.succeeded`, `MockProvider.requests`, an unused variable | Deleted |

### What was deliberately left alone, and why

* **`Workspace` is still a class.** It holds one value (the root directory) and five
  operations, and it is the single safety gate the whole project depends on. Turning it
  into free functions would mean passing the root into every call and into every tool,
  which spreads the safety rule out instead of keeping it in one place.
* **`Edit`, `FileChange`, `Action`, `TestResult`, `AgentOutcome` and `Config` are small
  dataclasses.** These are plain data records passed between steps, not abstractions —
  `change.diff` is easier to read and to check than `change["diff"]`.
* **The command validation in `test_runner.py`.** It looks fussy, but every line refuses
  a real way to smuggle a shell command in. It is the safety requirement, so I left it
  alone.
* **`protocol.py`'s prompt text.** It is long, but it is just instructions, and it is the
  only place the model is told what to do.

---

## 9. Limitations

* **The live API path is tested only at the unit level.** The scripted mock drives every
  test and the offline demo, and the HTTP request is built from the documented OpenAI
  format — but no test here has made a real network call, because that needs a key and
  would cost money. Treat your first real run as unverified until you see it work.
* The agent proposes **search-and-replace edits**, so it must quote existing text
  exactly. It recovers by re-reading the file, but it cannot create a new file or
  refactor broadly.
* The reply parser handles the usual cases (JSON wrapped in ``` fences or a sentence).
  A reply containing *several* JSON objects now raises a clear error and is retried,
  where a more complicated parser might have picked the first one.
* There is no memory between runs, no semantic/embedding search (`search_code` is
  literal or regex), and no automatic rollback — use git or `--dry-run`.
* `MAX_TOOL_CALLS` bounds the steps per attempt. A task needing more exploration is
  reported as `gave_up` rather than running forever.
