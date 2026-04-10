# Pre-commit and Pre-push Hooks

This document describes the local git-hook system for `bpetite`. Its purpose
is to catch violations of the repo contract (`CLAUDE.md`, the PRD, and the
task list) before they leave the developer's machine. It is a **partial
preflight** for the CI quality gate defined in `bpetite-prd-v2.md` FR-36 —
it runs a subset of the FR-36 commands (pytest and mypy) at push time but
does not currently run the repo-wide `ruff check .` / `ruff format --check .`
that FR-36 also mandates. CI remains authoritative. A clean local push
raises confidence that CI will pass, but it is not a guarantee.

---

## 1. Design

| Stage        | What runs                                                                    | Scope         | Speed target                  |
| ------------ | ---------------------------------------------------------------------------- | ------------- | ----------------------------- |
| `pre-commit` | Hygiene, ruff lint + format (check-mode), uv-lock, and six repo-local guards | Changed files | Sub-second on typical commits |
| `pre-push`   | `uv run pytest` and `uv run mypy --strict`                                   | Whole project | Matches CI quality gate       |

Rationale:

- The pre-commit stage must stay fast so that developers commit frequently.
  Every hook in this stage is file-scoped and runs only on staged paths.
- The pre-push stage runs `uv run pytest` and `uv run mypy --strict` as a
  partial preflight. It does **not** currently run repo-wide ruff checks,
  which FR-36 also requires — that parity fix lands with PRD task 1-4 once
  the CI workflow is authored. Until then, treat push-time success as a
  confidence signal, not a CI guarantee.
- During the pre-scaffold state (before PRD task 1-2 lands `pyproject.toml`
  and `uv.lock`), both pre-push hooks are **dormant**: they exit 0 with a
  stderr notice instead of attempting to run `uv run` against a project
  that does not yet exist. This prevents the hook system from claiming a
  guarantee it cannot honor.
- Ruff lint runs **before** ruff format, following Astral's ordering
  guidance: a lint fix may introduce code that requires reformatting.
- Ruff runs in **report-only** mode (no `--fix`, `--check` on format). The
  hook surfaces violations but does not silently mutate files on commit,
  matching the governance rule against silent refactors.

---

## 2. Bootstrap

First-time setup after cloning the repository:

```bash
# 1. Initialize the environment (installs pre-commit as a dev dependency).
uv sync

# 2. Install the git hooks declared in .pre-commit-config.yaml.
uv run pre-commit install
```

The second command reads `default_install_hook_types` from
`.pre-commit-config.yaml` and installs both `pre-commit` and `pre-push`
hooks into `.git/hooks/`.

If you clone before the initial scaffold lands (no `pyproject.toml` yet),
install `pre-commit` temporarily and run `pre-commit install` directly.

---

## 3. Commit-time hooks (runs on `git commit`)

### 3.1 Stock hygiene — `pre-commit/pre-commit-hooks` v6.0.0

| Hook ID                   | What it does                                                                                                                                                               |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `trailing-whitespace`     | Strips trailing whitespace from text files. Configured with `--markdown-linebreak-ext=md` so intentional two-space Markdown hard line breaks in `.md` files are preserved. |
| `end-of-file-fixer`       | Ensures text files end with exactly one newline.                                                                                                                           |
| `mixed-line-ending`       | Normalizes all line endings to LF (`--fix=lf`).                                                                                                                            |
| `check-merge-conflict`    | Blocks commits containing merge-conflict markers.                                                                                                                          |
| `check-case-conflict`     | Blocks filename clashes that break on case-insensitive filesystems.                                                                                                        |
| `check-added-large-files` | Blocks files over 500 KB being added (`--maxkb=500`).                                                                                                                      |
| `check-toml`              | Validates TOML syntax (e.g., `pyproject.toml`).                                                                                                                            |
| `check-yaml`              | Validates YAML syntax (e.g., this file, CI workflows).                                                                                                                     |
| `check-ast`               | Parses each Python file and blocks files with syntax errors.                                                                                                               |
| `debug-statements`        | Blocks committed `breakpoint()`, `pdb`, and similar debug statements.                                                                                                      |

### 3.2 Ruff — `astral-sh/ruff-pre-commit` v0.15.10

| Hook ID       | What it does                                        |
| ------------- | --------------------------------------------------- |
| `ruff-check`  | Runs `ruff check` in report-only mode (no `--fix`). |
| `ruff-format` | Runs `ruff format --check` (no rewrites).           |

To fix violations manually:

```bash
uv run ruff check --fix .
uv run ruff format .
```

### 3.3 uv lockfile — `astral-sh/uv-pre-commit` 0.11.6

| Hook ID   | What it does                                                                  |
| --------- | ----------------------------------------------------------------------------- |
| `uv-lock` | Regenerates `uv.lock` when `pyproject.toml`, `uv.toml`, or `uv.lock` changes. |

### 3.4 Repo-local guards — `scripts/hooks/`

All custom guards are stdlib-only Python scripts, portable across macOS and
Linux, and fail with specific, actionable error messages on violation.

| Hook ID                         | Scope                                                                                    | Rule enforced                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ------------------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `forbid-tests-init`             | `tests/__init__.py`                                                                      | Blocks `tests/__init__.py`. Tests must import from the installed package path.                                                                                                                                                                                                                                                                                                                                                                  |
| `forbid-syspath-hacks`          | `src/`, `tests/`, `scripts/` (except `scripts/hooks/`)                                   | AST-matches `sys.path.{insert,append,extend,pop,clear,remove}`, `sys.path = ...`, `sys.path[...] = ...`, `sys.path += ...`, `os.environ["PYTHONPATH"]` writes, and `os.putenv("PYTHONPATH", ...)`. Resolves common module-level aliases: `import sys as s; s.path.append(...)` and `from sys import path; path.append(...)` are caught, as are the `os` equivalents. Out of scope: local rebindings, `getattr` access, and string-based `exec`. |
| `forbid-generated-artifacts`    | All staged paths                                                                         | Blocks `data/tinyshakespeare.txt`, `data/tinyshakespeare-*.json`, any `data/*.json`, and `tokenizer.json` at the repository root. Patterns are **anchored by path-segment count**: `tokenizer.json` matches only repo-root `tokenizer.json`, not `fixtures/tokenizer.json`; `data/*.json` matches direct children of `data/` only, not `data/sub/foo.json`.                                                                                     |
| `forbid-core-networking`        | `src/bpetite/**/*.py`                                                                    | Blocks **direct** imports of `socket`, `ssl`, `urllib*`, `http*`, `ftplib`, `telnetlib`, `smtplib`, `smtpd`, `poplib`, `imaplib`, `nntplib`, `xmlrpc*`, `webbrowser`, `requests`, `httpx`, `aiohttp`, `urllib3`. Dynamic access via `importlib.import_module` or `subprocess` shells is not caught — that is out of AST scope and belongs to CI isolation.                                                                                      |
| `forbid-core-normalization`     | Tokenizer pipeline only: `_pretokenizer.py`, `_trainer.py`, `_encoder.py`, `_decoder.py` | AST-matches `.strip`/`.lstrip`/`.rstrip`/`.casefold`/`.lower`/`.upper`/`.title`/`.capitalize`/`.swapcase` method calls, `unicodedata.normalize(...)`, and any `import unicodedata`. Scoped narrowly to the tokenizer pipeline modules because PRD FR-6 targets that path specifically; CLI / support code under `src/bpetite/` may legitimately call these methods on non-token data.                                                           |
| `forbid-stdlib-re-in-tokenizer` | `src/bpetite/**/*.py`                                                                    | Blocks **direct** `import re` and `from re import ...`. The tokenizer must use `regex`. Dynamic access via `importlib.import_module("re")` is out of AST scope.                                                                                                                                                                                                                                                                                 |

---

## 4. Push-time hooks (runs on `git push`)

Both hooks use `language: system` and shell out to `uv run ...`, which runs
inside the `uv.lock`-pinned project environment. This guarantees zero drift
between what pre-push runs and what CI runs.

| Hook ID          | Command                | Scope         |
| ---------------- | ---------------------- | ------------- |
| `uv-mypy-strict` | `uv run mypy --strict` | Whole project |
| `uv-pytest`      | `uv run pytest`        | Whole project |

Both are declared with `pass_filenames: false, always_run: true` so they run
on every push regardless of which files changed (even docs-only pushes).

---

## 5. Manual invocation

Every hook can be run directly without committing or pushing.

```bash
# Run all pre-commit hooks on all files (manual lint/check pass).
# SKIP the approval sentinel because it only makes sense inside a real
# commit flow; without the skip, the guard fails immediately and the
# rest of the hook set never runs.
SKIP=require-commitall-approval uv run pre-commit run --all-files

# Run only the push-stage hooks on all files.
uv run pre-commit run --all-files --hook-stage pre-push

# Run a single hook by ID.
uv run pre-commit run ruff-check --all-files
uv run pre-commit run forbid-core-networking --all-files

# Run the underlying commands directly (subset of the FR-36 quality gate).
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict
```

The custom guard scripts are also runnable as plain Python:

```bash
scripts/hooks/forbid_core_networking.py src/bpetite/_trainer.py
scripts/hooks/forbid_generated_artifacts.py data/tinyshakespeare.txt
```

Exit code `0` means the file passes; any nonzero code means the hook fails.

---

## 6. Failure output format

Every repo-local guard renders its failures through a shared terminal UI
(`scripts/hooks/_ui.py`). Output uses stdlib-only ANSI and Unicode
light-single-line box-drawing characters (`U+2500..U+253C`) — the set with
the most consistent font coverage across macOS Terminal, iTerm2, Alacritty,
kitty, WezTerm, and GNOME Terminal.

Example (colors shown as semantic labels, not escape codes):

```text
┌─ forbid-core-networking ────────────────────── 2 violations ─┐
│                                                              │
│ src/bpetite/_trainer.py:1  import socket                     │
│ src/bpetite/_trainer.py:3  from urllib.request import ...    │
│                                                              │
│ help: The bpetite core library and CLI must not directly     │
│       import networking modules. Direct imports are blocked  │
│       here; dynamic imports and subprocess shells are out    │
│       of AST scope and must be caught by CI or sandboxing.   │
│       Remove the import or move the networked code into     │
│       scripts/ outside the package runtime path.             │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

Every panel contains exactly four sections:

1. **Title bar** — dim border, bold-red rule name on the left, dim-red
   violation count on the right.
2. **Violation list** — one row per violation. Location in cyan
   (`path[:line]`), detail in default foreground. Paths that exceed the
   panel width are truncated from the left with an ellipsis; details
   that exceed the remaining width are truncated from the right.
3. **Help paragraph** — bold-cyan `help:` label followed by a single
   wrapped paragraph explaining _why_ the rule exists and _what_ to fix.
   Hanging indent aligns continuation lines under the help text.
4. **Closing bar** — dim border.

**Color semantics (stable across all hooks):**

| Color     | Meaning                             |
| --------- | ----------------------------------- |
| Bold red  | The violated rule name              |
| Dim red   | Violation count                     |
| Cyan      | File path / location                |
| Bold cyan | The `help:` label                   |
| Dim       | Borders and structural chrome       |
| Default   | Violation detail and help body text |

**Color precedence:**

1. `NO_COLOR` set to any non-empty value → all colors suppressed (per
   [no-color.org](https://no-color.org)).
2. `FORCE_COLOR` set to any non-empty value → colors forced on.
3. Otherwise → colors enabled only if `stderr` is a TTY.

`NO_COLOR` wins over `FORCE_COLOR` — the conservative, accessibility-aware
ordering used by `rich` and `click`.

**Width handling:**

The panel width is `min(max(terminal_width, 60), 88)` columns. The minimum
of 60 prevents the title bar from collapsing into itself on unusually narrow
terminals; the maximum of 88 keeps output readable on wide monitors and
aligns with the repo's 88-column line-length convention.

**Output channel:**

All styled output is written to `stderr`. Pre-commit captures both streams
and displays them only on failure, so this keeps `stdout` clean and makes
it safe to pipe hook results through other tools.

**Success output:**

Silent. Pre-commit itself prints the `Passed` status line in green for every
successful hook; repeating that would be noise.

---

## 7. Refresh pinned revs

```bash
uv run pre-commit autoupdate
```

This rewrites the `rev:` fields under every `repo:` in
`.pre-commit-config.yaml` to each dependency's latest release tag. It does
not touch `repo: local` entries. Review the diff before committing.

---

## 8. Troubleshooting

**`pre-commit install` fails with "not a git repository".**
The repository must be initialized first: `git init`, then rerun.

**A stock hook fails with "Executable not found in environment".**
Delete the cache and reinstall the hook environments:
`pre-commit clean && uv run pre-commit install-hooks`.

**`uv-mypy-strict` or `uv-pytest` fails with "No `pyproject.toml` found".**
The scaffold (Task 1-2) has not landed yet. These hooks require an
initialized `uv` project. Run `uv sync` after the scaffold lands.

**A custom guard script fails with "Permission denied".**
Hook scripts must be executable. Restore the mode bit:
`chmod 755 scripts/hooks/*.py`.

**The custom guard reports a false positive on my file.**
Each guard has a precise, narrow scope. If you believe a rule is wrong,
open an issue describing the exact file and line, the rule that fired, and
why the code is legitimate. Do not loosen the check without a PRD update.

**Pre-push is too slow and I need to push a hotfix.**
Use `git push --no-verify` only in genuine emergencies. CI will catch any
regressions; fix them in a follow-up commit.

**Panel borders look misaligned in my terminal.**
This typically means your terminal is rendering some box-drawing characters
as double-width. The hook UI uses `U+2500..U+253C` exclusively (the narrow
single-line set); if your terminal font widens them, switch to a
monospaced font that supports the full box-drawing block (e.g. JetBrains
Mono, Menlo, Cascadia Code, Inconsolata).

---

## 9. Versions pinned today

| Tool                           | Rev        |
| ------------------------------ | ---------- |
| `pre-commit` framework minimum | `4.5.0`    |
| `pre-commit/pre-commit-hooks`  | `v6.0.0`   |
| `astral-sh/ruff-pre-commit`    | `v0.15.10` |
| `astral-sh/uv-pre-commit`      | `0.11.6`   |

Refresh with `uv run pre-commit autoupdate` and commit the rev bumps.
