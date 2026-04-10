---
name: commitall
description: Git commit approval workflow for repos using the sentinel-based commit guard. Use whenever the user runs `/commitall`, asks to commit changes, says "let's commit", "commit everything", "ship this", "ready to commit", or any similar intent. The skill first reconciles the project's auto-memory store against reality (Phase 0), then audits the working tree, drafts a Conventional Commits message, and hands off to the interactive scripts/commitall.sh which the user runs themselves. Never attempt a raw `git commit`; always route through this workflow.
---

# /commitall — Commit Approval Workflow

This skill governs the only approved path for committing changes in repos that
use the sentinel-based commit guard. A raw `git commit` is blocked by the
`require-commitall-approval` pre-commit hook. `scripts/commitall.sh` is
interactive (human-at-keyboard `read -p` prompts for the message and for y/N
approval), which means Claude cannot drive it end-to-end. Instead, Claude does
the pre-flight work, drafts the commit message, and hands off; the user runs
the script themselves in their own terminal.

## When To Invoke

- User runs `/commitall`.
- User says "commit everything", "let's commit", "ship this", "ready to
  commit", "commit this", or any similar intent to commit current working
  changes.
- User asks Claude to "run a commit" or "make a commit".

## Flow

Every invocation runs all five phases in order. Do not skip phases. Phase 0
runs before any other work so future Claude instances resuming this project
inherit an up-to-date picture of intent and state — not just the diff.

### Phase 0 — Memory Hygiene

**Goal:** reconcile the project's auto-memory store with reality before
touching the commit workflow. A stale memory is worse than no memory; a
missing memory loses context that the next session will have to rebuild
from scratch. This phase fixes both.

**Applicability:** only run Phase 0 if the current session has an auto-memory
system configured (described in the session system prompt, typically rooted
at `~/.claude/projects/<project-slug>/memory/` with a `MEMORY.md` index).
If no such system exists, print `memory: unavailable (skipped)` and proceed
to Phase 1. Do not create the directory yourself.

**Steps:**

1. **Read the index.** Load `MEMORY.md` in full. It is short by design; do
   not summarize or truncate. Note every entry, its title, and its
   one-line hook.
2. **Read each referenced memory file.** Every entry in `MEMORY.md` points
   to a sibling `.md` file with frontmatter (`name`, `description`, `type`).
   Load all of them. If a pointer is broken (file missing), queue the index
   line for removal.
3. **Reconcile against current reality.** For each memory, ask:
   - Does it reference a path, function, or flag that no longer exists?
     Verify with `Read`/`Grep`/`Glob` before deciding — a rename is not the
     same as a deletion.
   - Is it a "next step" or "pending" note whose work is now complete?
     (E.g. "planning to add CI" after CI has landed.)
   - Is it contradicted by a more recent decision captured earlier in this
     same session?
   - Is it a stale snapshot (activity log, inventory) whose freshness
     mattered at the time but no longer does?
   - Is it duplicated by `CLAUDE.md`, the PRD, the task list, or something
     derivable from `git log`? If so, it should not have been saved at
     all — remove it.
     Any **yes** means the memory is stale. **Update** it in place if only a
     detail is wrong; **delete** the whole file and its index line if the
     entire premise is gone.
4. **Capture new memory from the current session.** Walk the conversation
   from the start and extract anything that:
   - Is **not** already in `CLAUDE.md`, the PRD, the task list, or the
     current repo state.
   - Will be useful to a **future** Claude instance with no conversation
     history.
   - Fits one of the four auto-memory types:
     - **project** — design decisions, landing-order calls, deferred
       work with the reason for deferral, stakeholder asks, branch-
       protection gates not yet enabled, review verdicts, intentional
       PRD amendments. Use the required `**Why:**` and `**How to
apply:**` structure from the memory spec.
     - **feedback** — validated judgment calls from the user ("yes that
       was the right call"), corrections ("stop doing X"), or preferences
       discovered in passing. Always include the why so edge-case
       judgement is possible later.
     - **reference** — external system pointers (Linear project names,
       Grafana dashboards, Slack channels, doc links). Rare in this repo.
     - **user** — role/preferences/knowledge. Only add if you learned
       something **new** about Dinesh that isn't already captured.
       Do not save: code patterns, file paths, commit history, debugging
       recipes, or ephemeral task state. Those belong in the repo or the task
       list, not in memory.
5. **Write the deltas.** For each new or updated memory:
   - Create/overwrite the memory file with the required frontmatter
     (`name`, `description`, `type`) and a body that follows the
     type-specific structure (`**Why:**` + `**How to apply:**` for
     project/feedback types).
   - Update `MEMORY.md` with a single-line index entry: `- [Title](file.md)
— one-line hook`. Keep the index under 200 lines; truncation is
     silent above that bound.
   - Never write memory body content directly into `MEMORY.md`; it is an
     index, not a memory.
6. **Delete stale files.** For each memory queued for removal, delete the
   file and strike its line from `MEMORY.md`.
7. **Report.** Print a compact block before starting Phase 1:

   ```
   memory: <N> kept, <N> updated, <N> added, <N> removed
     + added:   <title>
     ~ updated: <title>
     - removed: <title> (<reason>)
   ```

   If nothing changed, print `memory: up to date (N entries)`. This block
   is part of the Phase 0 output; it does not replace the Phase 1 audit.

**Hard rules:**

- **Never skip Phase 0.** The user added it specifically so every commit
  is a memory checkpoint. If it is genuinely impossible (no memory system
  configured), say so explicitly in the skip notice.
- **Never write memory content that duplicates `CLAUDE.md`, the PRD, the
  task list, or anything derivable from `git log`.** Memory is for what the
  repo cannot already tell you.
- **Never save negative judgements about the user.** Memory exists to help
  future sessions be more useful, not to keep a ledger.
- **Never use memory to stash work-in-progress from the current
  conversation.** Task tracking and plans handle that; memory is only for
  information that should survive across sessions.
- **Verify before recommending from memory.** If a memory names a file or
  function, check that it still exists before relying on it in later
  phases. A memory is a claim about _the past_, not a live assertion.

### Phase 1 — Pre-flight Audit

Gather git state and scan for gotchas. All audits run on every invocation; the
cost is three git calls and one grep pass, sub-second.

1. **Git state survey:**
   - `git branch --show-current` — current branch
   - `git status --short`
   - `git diff --stat` (unstaged)
   - `git diff --cached --stat` (staged)
   - If no prior commits, note "initial commit, no HEAD yet".
   - If the current branch is `main` (the protected default per bpetite
     CLAUDE.md §Git Workflow), flag it: Phase 2 must propose a feature
     branch and Phase 3 must prepend branch creation to the hand-off.
     Committing directly to `main` is a governance violation; this skill
     never silently allows it.
2. **Grouping:** Bucket untracked/modified/staged paths by top-level directory
   so the user sees the shape of the commit at a glance.
3. **Red-flag scan (any hit → `BLOCKED` verdict):**
   - Any path whose size exceeds the `check-added-large-files` threshold in
     `.pre-commit-config.yaml` (currently 500 KB).
   - Any path that would be rejected by one of the six repo-local guards:
     - `tests/__init__.py`
     - `sys.path` mutations or `PYTHONPATH` writes in any `src/`, `tests/`,
       or `scripts/` file outside `scripts/hooks/`
     - Forbidden data artifacts (`data/tinyshakespeare.txt`,
       `data/tinyshakespeare-*.json`, `data/*.json`, `/tokenizer.json`)
     - Networking imports inside `src/bpetite/`
     - Normalization or trimming calls inside `src/bpetite/`
     - `import re` or `from re import` inside `src/bpetite/`
   - Suspected secret: grep the diff for `api_key`, `aws_secret`,
     `-----BEGIN`, `password=`, `token=`, `SECRET_KEY=`, private SSH key
     headers, or `.env` content.
4. **Soft-warn scan (any hit → `WARN` verdict, commit still drafted):**
   - Untracked paths that look cacheable but aren't in `.gitignore`
     (e.g. stray `__pycache__/`, editor state).
   - Unstaged modifications in a file whose directory also has staged
     changes — usually a sign of a forgotten change.
   - File-type surprises inside `src/bpetite/` (e.g. `.pyc`, `.so`, binary
     blobs).
5. **Quality gates (only if scaffold is in place):**
   - If `pyproject.toml` exists and `uv.lock` is present, run the four gates
     via `uv run`: `ruff check .`, `ruff format --check .`, `mypy --strict`,
     `pytest`. Any failure → `BLOCKED`.
   - If `pyproject.toml` does not exist yet (pre-Task-1-2 state), skip the
     gates and note "quality gates skipped: pre-scaffold".
6. **Verdict:** One of `READY`, `WARN`, or `BLOCKED` (see taxonomy below).

### Phase 2 — Message Draft

Skip this phase entirely on `BLOCKED` verdict. On `READY` or `WARN`:

- Draft a single-line Conventional Commits subject, imperative mood,
  **≤72 characters**. No body. No multi-line content. (The script's `read -p`
  only reads one line, and the repo convention is subject-only.)
- **Type** (from bpetite CLAUDE.md §Git Workflow): `feat`, `fix`, `chore`,
  `docs`, `refactor`, or `test`. Pick from the dominant change concern.
- **Scope:** short identifier for the affected area, auto-detected from
  changed paths. Examples: `hooks`, `cli`, `trainer`, `encoder`,
  `persistence`, `prd`, `tasks`, `docs`. Omit scope for cross-cutting work.
- **Subject:** imperative mood, no trailing period.
- **Protocol Zero:** zero AI attribution. No "generated by", "written by
  Claude", "AI-assisted", co-authored-by trailers, or self-referential AI
  language. Ever.
- **Split suggestion:** If the audit detected more than two unrelated
  concerns (e.g. `hooks/` + `docs/prd` + `data/`), surface a one-line note
  under the drafted message: "split suggestion: this could be committed as
  (1) feat(hooks): ..., (2) docs(prd): ..., (3) chore(data): ...". Do not
  split automatically. The user decides whether to break it up.
- **Branch name proposal:** Only when Phase 1 flagged the current branch
  as `main`. Draft a branch of the form `<type>/<short-kebab-slug>`:
  - `<type>` matches the commit type (`feat`, `fix`, `chore`, `docs`,
    `refactor`, `test`). bpetite CLAUDE.md explicitly names `feat/`,
    `fix/`, and `chore/`; the other commit types share the same
    taxonomy and are acceptable prefixes.
  - `<short-kebab-slug>` is a 2-5 word summary of the dominant concern,
    kebab-cased, lowercased, ≤40 characters. Derive it from the same
    signal that drove the commit subject; do not duplicate the full
    subject verbatim.
  - Example pairings:
    - `chore(scaffold): add bpetite package stubs` →
      `chore/scaffold-package-stubs`
    - `feat(trainer): add deterministic pair counting` →
      `feat/trainer-pair-counting`
    - `fix(cli): correct encode stderr channel` →
      `fix/cli-encode-stderr`
  - If Phase 1 reported a feature branch (any non-`main` branch), skip
    this bullet entirely. The user has already branched; inventing a new
    branch would strand their existing work.

### Phase 3 — Hand-off

Present a compact response with five sections in order:

1. **Audit block** — verdict, bucketed change summary, current branch, any
   warnings.
2. **Drafted message** — in a ` ``` ` code fence for copy-paste.
3. **Drafted branch** — only if Phase 2 proposed a branch. In a ` ``` `
   code fence alongside the message.
4. **Split suggestion** — only if applicable.
5. **Next step** — literal instructions. The exact command depends on
   whether a branch proposal is active.

   **If the user is already on a feature branch (no branch proposal):**

   > Run this in your prompt (the `!` prefix runs it in your shell so the
   > output lands in the conversation):
   >
   > ```
   > !bash scripts/commitall.sh
   > ```

   **If Phase 2 drafted a branch because the current branch is `main`:**

   > Run this in your prompt. The chain creates the feature branch first
   > so the commit lands on the branch, not on `main`:
   >
   > ```
   > !git checkout -b <drafted-branch> && bash scripts/commitall.sh
   > ```
   >
   > Substitute `<drafted-branch>` with the exact branch name from the
   > previous code fence.

   When the script prompts:

   - `Commit message:` — paste the drafted line above.
   - `Approve this commit? [y/N]` — type `y` and press Enter.

   The script's `trap cleanup EXIT` scrubs `.git/COMMIT_APPROVED` on every
   exit path, including Ctrl-C, so there is no cleanup burden on you.

Do not run `bash scripts/commitall.sh` yourself through the Bash tool. It
will hang on `read -p`.

### Phase 4 — Post-commit Verification

Wait for the user to report the outcome (the `!`-prefixed command pastes the
script's stdout/stderr into the next turn automatically). Then:

- **On success:** run `git log -1 --stat` and report one line:
  `committed: <short-sha> <subject> (N files, +X/-Y)`. Confirm
  `.git/COMMIT_APPROVED` is absent (sentinel cleanup worked). No further
  noise.
- **On failure:** diagnose from the script's output. Common causes:
  - `trailing-whitespace` or `end-of-file-fixer` auto-fixed files mid-commit.
    The commit fails with "files were modified by this hook". Tell the user
    the fixes are now in their working tree; re-run `/commitall` (the fixes
    will be included in the new diff).
  - `ruff-check` or `ruff-format --check` fails. Tell the user to run
    `uv run ruff check --fix .` and `uv run ruff format .`, then re-run
    `/commitall`.
  - `uv-mypy-strict` or `uv-pytest` fails at push time (not commit time) —
    that's the pre-push gate and runs on `git push`, not `/commitall`.
  - Sentinel still present on disk afterwards: something bypassed the trap
    (unlikely). Instruct the user to `rm -f .git/COMMIT_APPROVED`.

## Verdict Taxonomy

| Verdict   | Meaning                                                                         | Skill behaviour                                                                                                                      |
| --------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `READY`   | No red flags, no soft warnings. Clean for commit.                               | Draft message, hand off.                                                                                                             |
| `WARN`    | No red flags but at least one soft warning.                                     | Draft message, hand off with warnings surfaced in audit.                                                                             |
| `BLOCKED` | At least one red flag: oversized file, suspected secret, or guard-blocked path. | **Do not draft a message.** Surface the red flag and ask the user how to resolve. Only re-run the flow once the red flag is cleared. |

## Hard Rules

- **Never** run `git commit` directly — the pre-commit hook blocks it.
- **Never** invoke `bash scripts/commitall.sh` through the Bash tool — it is
  interactive and will hang.
- **Never** manually create or delete `.git/COMMIT_APPROVED`.
- **Never** pass `--no-verify` to skip the hook.
- **Never** add AI attribution to the commit message (Protocol Zero).
- **Never** draft multi-line bodies — the script reads one line only, and
  the repo convention is subject-only.
- **Never** proceed past `BLOCKED` without explicit resolution.
- **Never** allow a commit to land on `main`. If Phase 1 detects `main`
  as the current branch, Phase 2 must draft a branch name and Phase 3
  must prepend `git checkout -b <branch>` to the hand-off command. This
  enforces bpetite CLAUDE.md §Git Workflow ("Never push directly to
  `main`. All changes go through PRs.") at commit time, before the
  user has to back out a committed-to-main mistake by branching + hard-
  resetting.

## Edge Cases

- **Pre-scaffold state** (no `pyproject.toml`): quality gates are skipped,
  but the six repo-local guards still run via the commit hook. The first
  commit will typically be a single bundled "bootstrap" commit.
- **Empty working tree** (`git status --short` is empty): report "nothing
  to commit, working tree clean" and stop. Do not hand off.
- **No HEAD yet** (initial commit): `git diff --cached --stat` will be
  empty. Frame the audit as "initial commit: N untracked paths".
- **Auto-fix hooks modified files**: the first `/commitall` attempt may fail
  because `trailing-whitespace` or `end-of-file-fixer` rewrote files. Those
  fixes are now in the working tree. Re-run `/commitall` — the second pass
  will include the auto-fixes in the diff and succeed.
- **Partial staging** (`git add -p` already used): the current `commitall.sh`
  runs `git add -A` before `git commit`, which defeats partial staging. If
  the user has explicitly partial-staged, warn them that `git add -A` will
  pull in the rest, and ask whether to proceed.
- **Current branch is `main`**: Phase 2 must draft a branch name, Phase 3
  must prepend `git checkout -b <branch>` to the hand-off command. Never
  allow the commit to land on `main` — that is a bpetite CLAUDE.md §Git
  Workflow violation and forces a branch-and-reset recovery dance after
  the fact.
- **Detached HEAD or a non-standard branch** (e.g. an `exp/*` throwaway):
  surface the state in the audit, do not propose a new branch, and ask
  the user to confirm the current branch is the intended commit target
  before handing off.

## If The Script Doesn't Exist

If `scripts/commitall.sh` is missing, the repo has not been set up yet. Tell
the user:

> `scripts/commitall.sh` not found. Run `bash setup-hooks.sh` to initialize
> the commit approval system before committing.

Do not attempt to recreate the script from memory. Direct the user to run
setup.
