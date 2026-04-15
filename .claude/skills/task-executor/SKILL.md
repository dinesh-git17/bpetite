---
name: task-executor
description: Executes a single task from the bpetite task list with full procedural rigor. Reads the complete task schema before touching any code, confirms all dependencies are met, implements only what is in scope, runs the four required quality gates, verifies every acceptance criterion individually, and reports pass/fail per criterion before stopping. Ends with an explicit hold — never proceeds to the next task automatically. Use this skill at the start of every task execution. Invoke with /task-executor. Also triggers automatically when you say "implement task", "start task", "work on task", "pick up task", "execute task", or name a specific bpetite task ID like "work on task 2-3" or "let's do 3-1".
---

# task-executor

A procedural execution skill for `bpetite` tasks. The goal is to make "I implemented it" mean "I implemented it and verified every acceptance criterion" — every single time, without scope creep, premature completion, or skipped verification.

Multi-phase projects are where Claude Code most often goes wrong: it drifts into adjacent work, declares done before all criteria are verified, or skips the quality gates when they seem obvious. This skill exists to close that gap with a mandatory, step-by-step procedure for every task.

---

## Required inputs

Before starting, you need:

1. **The task ID** — e.g. `2-3`, `3-1`, `4-2`. If the user has not specified one, ask for it. Do not guess.
2. **The task list** — located at `docs/bpetite-task-list.md` in the repo. Read it now if you have not already.
3. **The PRD** — located at `docs/bpetite-prd-v2.md`. Read it for constraint context before touching implementation.

---

## Step 1 — Read the full task schema

Before writing a single line of code, read the complete entry for the target task in `docs/bpetite-task-list.md`.

Extract and hold in working context:

- **Objective** — what this task accomplishes
- **Deliverables** — the exact files that must exist when the task is done
- **Dependencies** — which tasks or phase exit gates must be complete first
- **Implementation Notes** — specific constraints and decisions already made for you
- **Acceptance Criteria** — the numbered list you will verify, one by one, at the end
- **Owner** — whether this task is `Claude Code`, `Human engineer`, or `Human engineer + Claude Code`

If the task is not owned by `Claude Code` or `Human engineer + Claude Code`, stop and tell the user. Do not attempt human-required tasks (like `1-3`, `1-4`, `4-4`, `4-6`) autonomously — they require machine execution, external validation, or GitHub access you cannot provide.

---

## Step 2 — Confirm prerequisites

Dependencies in bpetite are real execution gates, not suggestions. Before writing any code:

1. Check each listed dependency (prior task IDs and phase exit gates).
2. For each dependency, confirm it is complete. The evidence is: the deliverables it required exist in the repo AND the tests that gate it pass.
3. If any dependency is not satisfied, stop. Report what is missing and ask the user to confirm before proceeding.

The task list is explicit: **phase exit gates are mandatory**. Do not start Phase N work if the Phase N-1 exit gate is not green.

---

## Step 3 — Implement only what is in scope

Implement exactly the deliverables listed for this task, following the implementation notes precisely.

### Standing constraints (always active, no exceptions)

These rules come directly from the task list's Non-Negotiable Implementation Rules section and apply to every task:

- Python 3.12 only. macOS and Linux only.
- Core algorithm code must remain pure Python. No Rust, no C extensions, no external tokenizer libraries.
- `regex` and `rich` are the only permitted runtime dependencies beyond the standard library (`rich` is scoped to the CLI presentation layer and must never appear in the core algorithm import path).
- No normalization, case folding, prefix-space insertion, or whitespace trimming anywhere in the pipeline.
- `vocab_size` always refers to mergeable vocabulary size, excluding reserved special tokens.
- The only reserved special token in v1 is the exact literal `<|endoftext|>`.
- Tests must import the installed package path, not mutate `PYTHONPATH`.
- `pytest` must run in `importlib` import mode.
- CLI machine-readable results go to `stdout` only. Progress and errors go to `stderr` only.
- Core library and CLI must not perform network calls.
- Generated corpora, generated tokenizer artifacts, caches, and virtual environments must not be committed.

### Scope discipline

- Implement the deliverables for this task. Not the next task. Not a "while I'm here" refactor.
- If you notice a bug or improvement in code you are not changing, note it and leave it for later. Do not fix it now.
- If the implementation notes say "expose `X`", expose exactly `X`. Do not also expose `Y` because it seems useful.
- If a constant is defined in `_constants.py`, import it. Do not re-define it locally.

---

## Step 4 — Run all four quality gates in order

When implementation is complete, run these four commands in this exact order. Do not skip any. Do not reorder them.

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict
```

Each gate must exit `0`. If any gate fails:

1. Report the exact failure.
2. Fix it.
3. Re-run **all four gates from the beginning** — not just the one that failed. A fix for one gate sometimes breaks another.
4. Repeat until all four are green in a single complete run.

Do not move to Step 5 until all four gates exit `0` together.

---

## Step 5 — Verify each acceptance criterion individually

Read the Acceptance Criteria from the task schema you extracted in Step 1. Go through them one by one. For each criterion:

- State the criterion.
- Show the evidence that it passes (test output, file existence check, code review, command output — whatever is appropriate).
- Mark it **PASS** or **FAIL**.

Do not bundle criteria. Do not say "all criteria pass" without showing each one. The point is to catch the one criterion that looks obviously true but actually isn't.

If any criterion **FAILs**:

- Fix the implementation.
- Re-run all four quality gates (Step 4 in full).
- Re-verify the failing criterion and any others that could have been affected.

---

## Step 6 — Report and hold

When all quality gates are green and all acceptance criteria are verified, produce a final report in this format:

```
## Task [ID] — [Title]

### Quality gates
- [x] uv run pytest
- [x] uv run ruff check .
- [x] uv run ruff format --check .
- [x] uv run mypy --strict

### Acceptance criteria
1. [criterion text] — PASS
2. [criterion text] — PASS
...

### Deliverables created
- [file path]
- [file path]
...

### Status: COMPLETE

---
⛔ Stopped. The next task is [N+1 ID — Title].
Do not proceed until you explicitly ask me to start it.
```

**Do not start the next task.** Do not mention what you might do next. Do not suggest it. Stop here and wait for an explicit instruction.

The reason this rule exists: auto-continuation is how phase drift happens. The next task may have different prerequisites, different scope, or require a human gate. Every task starts with Step 1 of this skill.

---

## Common failure modes to avoid

**Premature declaration of done** — Do not say "done" or "complete" until Step 6 is written out. The quality gates and criterion checklist must exist in the output.

**Skipping implementation notes** — The implementation notes in each task contain decisions that are already made. They are not suggestions. If a note says "expose `encode(text, merges, special_tokens)`", that is the function signature. Do not redesign it.

**Chunk-boundary test anti-pattern** — Task 2-6 has a specific note about this. The correct chunk-boundary test proves "no merge across boundaries" using a crafted negative corpus, not by scanning the final merge list for boundary pairs. Do not use the incorrect heuristic.

**Implicit type coercions** — The PRD requires strict byte typing. `bytes`, `bytearray`, and `memoryview` are not interchangeable. Be explicit.

**`tests/__init__.py`** — This file must not exist. Its presence breaks the `importlib` import mode requirement. If you accidentally create it, remove it.

**Committing generated artifacts** — `data/tinyshakespeare.txt`, `data/tinyshakespeare-*.json`, and any trained tokenizer artifacts must not be tracked. Check `.gitignore` before creating files outside `src/` and `tests/`.
