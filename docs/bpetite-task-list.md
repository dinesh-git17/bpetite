# Implementation Task List: bpetite v1.0

**Source PRD:** `docs/bpetite-prd-v2.md`  
**PRD version:** v3.0  
**Status:** Handoff ready  
**Last updated:** April 7, 2026

## Purpose

This document is the implementation handoff plan for `bpetite` v1.0. It translates the PRD into an execution-ready task list with explicit sequencing, dependencies, acceptance criteria, and phase exit gates.

If this document conflicts with the PRD, the PRD wins.

## Non-Negotiable Implementation Rules

- Python 3.12 is the only supported interpreter for v1.
- macOS and Linux are the only supported execution targets for v1.
- Core algorithm code must remain pure Python.
- `regex` is the only runtime dependency beyond the standard library.
- Development dependencies must be declared as local development dependencies, not published extras.
- No task may introduce normalization, case folding, prefix-space insertion, or whitespace trimming anywhere in the pipeline.
- `vocab_size` always refers to mergeable vocabulary size and excludes reserved special tokens.
- The only reserved special token in v1 is the exact literal `<|endoftext|>`.
- Tests must import the installed package path, not mutate `PYTHONPATH`.
- `pytest` must run in `importlib` import mode.
- CLI machine-readable results go to `stdout` only.
- CLI progress updates and human-readable errors go to `stderr` only.
- Core library and CLI must not perform network calls.
- Generated corpora, generated tokenizer artifacts, caches, and virtual environments must not be committed.
- Phase exit gates are mandatory. Do not start the next phase until the current phase exit gate is green.
- No task text may use `TBD`, `etc.`, `as needed`, or similarly vague language.

## Task ID Scheme

- `1-x`: Phase 1, scaffolding and tooling
- `2-x`: Phase 2, core algorithm, fixtures, and persistence
- `3-x`: Phase 3, encode/decode and public API
- `4-x`: Phase 4, CLI, docs, benchmarks, and release gate
- `5-x`: Phase 5, optional reference comparison

## Ownership Conventions

- `Claude Code`: safe to implement entirely in-code within the repo
- `Human engineer`: requires machine-specific execution, external validation, or GitHub verification
- `Human engineer + Claude Code`: Claude drafts the code or document; human performs the final machine-specific validation

---

## ~~Phase 1: Scaffolding and Tooling~~

> **Phase complete 2026-04-10.** All four tasks resolved; see individual task headings and the Phase 1 Exit Gate for details.

**Goal:** Create a reproducible repo foundation with the correct package layout, lockfile discipline, test import behavior, and hardened CI.

### ~~Task 1-1: Create Repo Scaffold and Ignore Policy~~

#### Objective

Create the package tree, test tree, script directories, and ignore rules required for the project foundation.

#### Deliverables

- `src/bpetite/__init__.py`
- `src/bpetite/_cli.py`
- `src/bpetite/_constants.py`
- `src/bpetite/_pretokenizer.py`
- `src/bpetite/_trainer.py`
- `src/bpetite/_encoder.py`
- `src/bpetite/_decoder.py`
- `src/bpetite/_persistence.py`
- `src/bpetite/_tokenizer.py`
- `tests/fixtures/`
- `data/`
- `scripts/`
- `README.md` placeholder
- `.gitignore`

#### Dependencies

- None

#### Implementation Notes

- Use the `src/` layout unconditionally.
- Do not create `tests/__init__.py`. The test suite must validate the installed package path, not rely on repository-root import side effects.
- Add stub module bodies that are valid under Python 3.12.
- `.gitignore` must include at minimum:
  - `.venv/`
  - `.pytest_cache/`
  - `.mypy_cache/`
  - `.ruff_cache/`
  - `data/tinyshakespeare.txt`
  - `data/tinyshakespeare-*.json`

#### Acceptance Criteria

1. The package tree exists under `src/bpetite/` with all required stub modules.
2. `tests/fixtures/`, `data/`, and `scripts/` exist.
3. `.gitignore` excludes local environments, caches, downloaded corpora, and generated tokenizer artifacts.
4. `python -m py_compile src/bpetite/*.py` exits `0`.
5. `tests/__init__.py` does not exist.

#### Owner

- Claude Code

### ~~Task 1-2: Configure `pyproject.toml` and Tooling~~

#### Objective

Create a complete `pyproject.toml` that defines package metadata, the console entry point, development dependencies, and tool configuration.

#### Deliverables

- `pyproject.toml`

#### Dependencies

- Task 1-1

#### Implementation Notes

- Use `hatchling` as the build backend.
- Set:
  - package name: `bpetite`
  - version: `0.1.0`
  - `requires-python = ">=3.12"`
  - `project.dependencies = ["regex"]`
- Define development dependencies in `[dependency-groups]`:
  - `dev = ["pytest", "ruff", "mypy", "tiktoken"]`
- Define the console script:
  - `bpetite = "bpetite._cli:main"`
- Configure pytest to use `importlib` mode.
- Configure `ruff`, `ruff format`, and `mypy --strict`.
- Under mypy configuration, use a stable source-path setting that works from the repo root, e.g. `$MYPY_CONFIG_FILE_DIR/src`.
- Enable `warn_unused_configs = true` in mypy.

#### Acceptance Criteria

1. `pyproject.toml` includes package metadata, the `bpetite` console script, runtime dependency `regex`, and a `dev` dependency group.
2. `tiktoken` is declared only as a development dependency.
3. pytest is configured for `--import-mode=importlib`.
4. mypy is configured for strict checking.
5. No published optional dependency is used to model local development tooling.

#### Owner

- Claude Code

### ~~Task 1-3: Generate and Commit the Lockfile~~

#### Objective

Create the initial lockfile and verify the editable local environment.

#### Deliverables

- `uv.lock`

#### Dependencies

- Task 1-2

#### Implementation Notes

- Generate the environment and lockfile with `uv sync`.
- After the lockfile exists, future local setup and CI must use locked sync.
- Verify the package imports from the installed environment, not from ad hoc path hacks.

#### Acceptance Criteria

1. `uv.lock` exists and is committed.
2. `uv run python -c "import bpetite"` exits `0`.
3. `uv run pytest --collect-only` exits `0`.
4. `uv run mypy --strict` runs without import-path errors on the scaffold.

#### Owner

- Human engineer

### ~~Task 1-4: Configure Hardened GitHub Actions CI~~

> **Resolved 2026-04-10 (PR #4).** The literal deliverable `.github/workflows/ci.yml` was not created. Instead, the CI workflow set landed ahead of Phase 1 in commit `dc0a314` as eleven separate workflows (`tests`, `lint`, `format`, `types`, `build`, `cli-smoke`, `determinism`, `import-smoke`, `policy-guard`, `syntax`, `ci-meta`) plus support workflows under `.github/workflows/`. Each workflow uses `uv sync --locked`, `contents: read` workflow-level permissions with narrow per-job elevations, `timeout-minutes` on every job, and SHA-pinned remote action references with trailing `# vX.Y.Z` comments. `tests` and `cli-smoke` run on both `ubuntu-latest` and `macos-latest`; the remaining gates run on `ubuntu-latest` only. All six acceptance criteria below are satisfied by the existing set. The original task body is preserved for historical context.

#### Objective

Create a CI workflow that validates the repo on macOS and Linux with locked dependency installs and the PRD quality gates.

#### Deliverables

- `.github/workflows/ci.yml`

#### Dependencies

- Task 1-3

#### Implementation Notes

- Use GitHub Actions matrix builds for Python `3.12`.
- Run `tests` and `cli-smoke` on both `ubuntu-latest` and `macos-latest` (they exercise runtime paths that can drift across operating systems).
- Run `lint`, `format`, `type`, `build`, `determinism`, `policy-guard`, and `syntax` on `ubuntu-latest` only. Their underlying tools (`ruff`, `mypy`, `uv build`, `py_compile`, AST-based policy scripts) are OS-invariant by construction, so a second OS run would consume Actions minutes without catching additional regressions.
- Use the official `astral-sh/setup-uv` action.
- Pin every remote action reference by 40-character commit SHA with a trailing `# vX.Y.Z` release comment. Mutable major tags (`@v4`) are forbidden for remote actions because an upstream move can silently alter CI behavior. Local composite actions under `./.github/actions/**` are exempt. Dependabot manages the SHA bumps.
- Set minimal workflow permissions at the workflow level:
  - `contents: read`
- Elevate permissions only on the specific jobs that need them (`pull-requests: write` for comment automation, `security-events: write` for CodeQL, `issues: write` for label sync).
- Add `timeout-minutes` to every job.
- Use locked dependency sync in CI:
  - `uv sync --locked`
- Run the exact PRD quality-gate commands:
  - `uv run pytest`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run mypy --strict`

#### Acceptance Criteria

1. The workflow runs on push and pull request.
2. `tests` and `cli-smoke` execute on both `ubuntu-latest` and `macos-latest`; the remaining required gates execute on `ubuntu-latest` only.
3. The workflow uses locked dependency installation.
4. The workflow uses least-privilege permissions.
5. Every remote action reference is pinned by 40-character commit SHA with a trailing `# vX.Y.Z` comment.
6. The workflow is green on the scaffold commit.

#### Owner

- Human engineer + Claude Code

### ~~Phase 1 Exit Gate~~

> **Closed 2026-04-10 (PR #4 merged).** All four bullets satisfied: `src/` layout landed in PR #1; `uv.lock` committed in PR #4; tests import via the installed package path (verified by `tests/test_smoke.py`); CI green on both `ubuntu-latest` and `macos-latest`.

- Repo structure exists under `src/`.
- Lockfile is committed.
- Tests import via the installed package path.
- CI passes on `ubuntu-latest` and `macos-latest`.

---

## Phase 2: Core Algorithm, Fixtures, and Persistence

**Goal:** Implement the canonical regex pre-tokenizer, deterministic trainer, atomic persistence layer, and the full determinism proof required by the PRD.

### Task 2-1: Create Shared Constants and Core Contracts

#### Objective

Centralize the canonical constants that must not drift across modules.

#### Deliverables

- `src/bpetite/_constants.py`

#### Dependencies

- Phase 1 exit gate

#### Implementation Notes

- Define shared constants for:
  - the canonical pre-tokenizer regex string
  - schema version `1`
  - the literal special token `<|endoftext|>`
- Import these constants from the core modules instead of repeating string literals.

#### Acceptance Criteria

1. The canonical regex string exists in exactly one module-level source of truth.
2. The schema version exists in exactly one module-level source of truth.
3. The special token literal exists in exactly one module-level source of truth.
4. `_pretokenizer.py`, `_trainer.py`, `_encoder.py`, and `_persistence.py` import these constants instead of hardcoding local copies.

#### Owner

- Claude Code

### Task 2-2: Add Deterministic Test Fixtures

#### Objective

Commit the exact fixtures required for deterministic unit, integration, and CLI tests.

#### Deliverables

- `tests/fixtures/tiny.txt`
- `tests/fixtures/unicode.txt`
- `tests/fixtures/empty.txt`
- `tests/fixtures/invalid_utf8.bin`
- `tests/conftest.py`

#### Dependencies

- Phase 1 exit gate

#### Implementation Notes

- `tiny.txt` must be a small deterministic training corpus that produces multiple merges at `vocab_size=260`.
- `unicode.txt` must contain:
  - emoji
  - CJK
  - Arabic
  - whitespace-only lines
  - at least one literal `<|endoftext|>`
- `empty.txt` must be exactly `0` bytes.
- `invalid_utf8.bin` must contain bytes that fail strict UTF-8 decoding and is used only for CLI file-read failure tests.
- `conftest.py` should expose fixtures for the text corpora using UTF-8 reads and a fixture that exposes the invalid UTF-8 file path as a `Path`.

#### Acceptance Criteria

1. All four fixture files exist.
2. `empty.txt` is exactly `0` bytes.
3. `unicode.txt` contains all required categories.
4. `uv run pytest --collect-only` loads `tests/conftest.py` without error.

#### Owner

- Claude Code

### Task 2-3: Implement the Pre-tokenizer

#### Objective

Implement the canonical GPT-2-style regex pre-tokenizer as a pure function that preserves all source characters exactly.

#### Deliverables

- `src/bpetite/_pretokenizer.py`

#### Dependencies

- Task 2-1

#### Implementation Notes

- Expose `pretokenize(text: str) -> list[bytes]`.
- Use the `regex` package, not the standard-library `re` module.
- Compile the canonical pattern once at module import time.
- Return chunks in source order as UTF-8 bytes.
- `pretokenize("")` must return `[]`.

#### Acceptance Criteria

1. The exact PRD regex is used.
2. `b"".join(pretokenize(text)) == text.encode("utf-8")` for representative ASCII and Unicode inputs.
3. `pretokenize("") == []`.
4. No normalization or whitespace trimming occurs anywhere in the implementation.

#### Owner

- Claude Code

### Task 2-4: Add Pre-tokenizer Unit Tests

#### Objective

Verify the pre-tokenizer in isolation before trainer work depends on it.

#### Deliverables

- `tests/test_pretokenizer.py`

#### Dependencies

- Task 2-2
- Task 2-3

#### Implementation Notes

- Cover:
  - empty string
  - ASCII text
  - whitespace-only text
  - emoji, CJK, and Arabic
  - contractions such as `"don't"`, `"I'll"`, and `"we've"`
  - mixed punctuation and alphanumeric text
- Assert byte-preserving concatenation for every tested input.

#### Acceptance Criteria

1. All FR-4 to FR-6 behaviors are covered by tests.
2. `uv run pytest tests/test_pretokenizer.py` exits `0`.
3. `uv run ruff check .` and `uv run mypy --strict` remain green after the test file is added.

#### Owner

- Claude Code

### Task 2-5: Implement the Deterministic Trainer

#### Objective

Implement deterministic byte-level BPE training, special-token reservation, and internal progress-event support.

#### Deliverables

- `src/bpetite/_trainer.py`

#### Dependencies

- Task 2-1
- Task 2-3

#### Implementation Notes

- Expose internal training support sufficient for the public API to call:
  - deterministic pair counting
  - lexicographic tie-breaking using normal Python tuple ordering
  - non-overlapping left-to-right merge replacement
  - early-stop if no mergeable pairs remain
  - special token reservation after merge training
- The trainer does not extract or special-case `<|endoftext|>` during training. If the training corpus contains that literal string, it is pre-tokenized and merged like any other text. Special token reservation happens only after merge training completes (per FR-15).
- Preserve strict byte typing. Do not rely on implicit coercions between `bytes`, `bytearray`, and `memoryview`.
- Add an internal optional progress callback so later CLI work can emit:
  - start
  - every 100 merges actually completed
  - completion
- The public `Tokenizer.train` API must remain exactly `train(corpus: str, vocab_size: int)`.

#### Acceptance Criteria

1. `train(corpus, vocab_size < 256)` raises `ValueError`.
2. `train(corpus, 256)` returns the base vocabulary, zero merges, and the reserved special token at ID `256`.
3. Tie-breaking selects the lexicographically smallest tied pair.
4. Merge application is non-overlapping and left-to-right.
5. Early-stop returns the actual learned mergeable vocabulary size without error.
6. The internal progress callback API exists and does not alter the public `Tokenizer.train` signature.

#### Owner

- Claude Code

### Task 2-6: Add Trainer Unit Tests

#### Objective

Prove trainer correctness before persistence or encode/decode work builds on it.

#### Deliverables

- `tests/test_trainer.py`

#### Dependencies

- Task 2-2
- Task 2-5

#### Implementation Notes

- Cover:
  - `vocab_size < 256`
  - `vocab_size == 256`
  - empty corpus
  - deterministic repeated training
  - merge order
  - tie-breaking with a crafted corpus
  - non-overlapping merge behavior
  - early-stop behavior
  - special-token placement
  - progress callback event schedule
- Do not use the invalid heuristic "boundary pairs must never appear in merges".
- For the chunk-boundary test, use a crafted corpus where the candidate pair exists only across pre-tokenizer chunk boundaries and nowhere within a chunk.

#### Acceptance Criteria

1. All FR-7 to FR-15 requirements are covered.
2. The chunk-boundary test proves "no merge across boundaries" using a crafted negative case, not by scanning the final merge list for arbitrary boundary pairs.
3. `uv run pytest tests/test_trainer.py` exits `0`.

#### Owner

- Claude Code

### Task 2-7: Implement Atomic Save and Validating Load

#### Objective

Implement persistence with stable serialized bytes, atomic writes, and strict load-time validation.

#### Deliverables

- `src/bpetite/_persistence.py`

#### Dependencies

- Task 2-1
- Task 2-5

#### Implementation Notes

- Expose:
  - `save(path: str, vocab: dict[int, bytes], merges: list[tuple[int, int]], special_tokens: dict[str, int], overwrite: bool = False) -> None`
  - `load(path: str) -> tuple[dict[int, bytes], list[tuple[int, int]], dict[str, int]]`
- Save must:
  - fail with `FileExistsError` when `overwrite=False` and the destination exists
  - fail with `FileNotFoundError` when the parent directory is missing
  - write to a temporary file in the destination directory
  - replace the final path atomically
  - serialize deterministically with fixed key ordering and fixed separators
- Load must validate:
  - valid JSON syntax
  - duplicate JSON object keys are rejected during parse (Python's `json.loads` silently accepts duplicates by default — use `object_pairs_hook` to detect and reject them)
  - `schema_version == 1`
  - required keys are present
  - `pretokenizer_pattern` exactly matches the canonical pattern
  - `mergeable_vocab_size == len(merges) + 256`
  - vocab keys are decimal strings coercible to unique integer IDs
  - vocab values are lists of integers in `0..255`
  - merge entries are lists of exactly two integers
  - the special-token mapping is exactly `{"<|endoftext|>": <id>}`
  - the special-token ID is the first token ID greater than or equal to the mergeable vocabulary size
  - the special-token ID is present in vocab and maps to the UTF-8 bytes of the literal special-token string
- Loader behavior must remain data-only JSON parsing. No code execution, no imports from artifact content.

#### Acceptance Criteria

1. Save is atomic and overwrite-safe.
2. Saved artifact bytes are deterministic for the same in-memory tokenizer state.
3. Loader rejects malformed JSON, duplicate keys, schema mismatches, malformed shapes, invalid byte values, and special-token inconsistencies with typed exceptions.
4. Loader reconstructs a tokenizer state that preserves identical encode/decode behavior.

#### Owner

- Claude Code

### Task 2-8: Add Persistence Tests and the Determinism Gate

#### Objective

Prove persistence correctness and satisfy the PRD determinism release requirement with direct artifact-byte comparisons.

#### Deliverables

- `tests/test_persistence.py`

#### Dependencies

- Task 2-2
- Task 2-5
- Task 2-7

#### Implementation Notes

- Cover:
  - round-trip save/load
  - overwrite protection
  - overwrite success
  - missing parent directory
  - malformed JSON
  - duplicate JSON object keys
  - missing required keys
  - invalid byte values
  - malformed merges
  - schema version mismatch
  - `mergeable_vocab_size` mismatch
  - regex pattern mismatch
  - special-token mismatch
- Add two determinism proofs:
  - same `(vocab, merges, special_tokens)` saved twice produces identical bytes
  - training the same corpus twice and saving both artifacts produces identical bytes

#### Acceptance Criteria

1. `load(save(...))` returns an identical tokenizer state.
2. Saving the same tokenizer state twice produces identical file bytes.
3. Training the same corpus twice at the same `vocab_size` and saving both results produces identical artifact bytes.
4. `uv run pytest tests/test_persistence.py` exits `0`.

#### Owner

- Claude Code

### Phase 2 Exit Gate

- Pre-tokenizer tests are green.
- Trainer tests are green.
- Persistence tests are green.
- Repeated training on the same corpus produces byte-identical artifacts.

---

## Phase 3: Encode, Decode, and Public API

**Goal:** Implement the end-to-end tokenizer behavior and prove `decode(encode(text)) == text` for all required input classes.

### Task 3-1: Implement the Encoder

#### Objective

Implement encoding with exact special-token extraction, canonical pre-tokenization of non-special segments, and merge-rank application.

#### Deliverables

- `src/bpetite/_encoder.py`

#### Dependencies

- Phase 2 exit gate

#### Implementation Notes

- Expose `encode(text: str, merges: list[tuple[int, int]], special_tokens: dict[str, int]) -> list[int]`.
- Split only on exact literal `<|endoftext|>` occurrences.
- Treat partial strings such as `<|endoftext` as ordinary text.
- Apply learned merges by iterating through the merge list in rank order. For each ranked merge, scan the chunk's current token list and replace all non-overlapping occurrences left-to-right, matching the training-time replacement semantics from FR-10.
- Keep special-token extraction outside the pre-tokenizer.

#### Acceptance Criteria

1. `encode("") == []`.
2. A single exact special token encodes as one special-token ID.
3. Multiple consecutive special tokens encode as multiple special-token IDs in order.
4. Partial special-token strings are encoded as ordinary text.
5. Merge application iterates through merges in rank order. Within each rank, replacements are non-overlapping and left-to-right.
6. When the same merge applies multiple times in one chunk (e.g., bytes `[a, b, a, b]` with merge `(a, b)`), all non-overlapping left-to-right occurrences are replaced in a single pass for that merge rank.

#### Owner

- Claude Code

### Task 3-2: Implement the Decoder

#### Objective

Implement decoding against the stored vocabulary with strict UTF-8 behavior.

#### Deliverables

- `src/bpetite/_decoder.py`

#### Dependencies

- Phase 2 exit gate

#### Implementation Notes

- Expose `decode(token_ids: Sequence[int], vocab: dict[int, bytes]) -> str`.
- Concatenate all token bytes first, then decode once with UTF-8 strict mode.
- Let `KeyError` and `UnicodeDecodeError` propagate naturally.
- Decoding the reserved special-token ID must produce the literal string because its vocab entry stores the literal UTF-8 bytes.

#### Acceptance Criteria

1. `decode([]) == ""`.
2. Unknown IDs raise `KeyError`.
3. Invalid concatenated UTF-8 bytes raise `UnicodeDecodeError`.
4. The function type accepts `Sequence[int]`.

#### Owner

- Claude Code

### Task 3-3: Implement the Public `Tokenizer` API

#### Objective

Wire the trainer, encoder, decoder, and persistence layer into the exact public API required by the PRD.

#### Deliverables

- `src/bpetite/_tokenizer.py`
- updated `src/bpetite/__init__.py`

#### Dependencies

- Task 3-1
- Task 3-2

#### Implementation Notes

- Expose exactly these public methods:
  - `Tokenizer.train`
  - `Tokenizer.encode`
  - `Tokenizer.decode`
  - `Tokenizer.save`
  - `Tokenizer.load`
- Export only `Tokenizer` from `bpetite.__init__`.
- Keep instance state private.
- `Tokenizer.encode` must call the encoder with the method argument `text`, not any stored text attribute.

#### Acceptance Criteria

1. `from bpetite import Tokenizer` resolves without error.
2. No public names other than `Tokenizer` are exported from `bpetite`.
3. `Tokenizer.train(tiny_corpus, 260)` returns a `Tokenizer` instance.
4. The public method set matches the PRD exactly.

#### Owner

- Claude Code

### Task 3-4: Add Roundtrip and Public API Tests

#### Objective

Prove end-to-end correctness using the public API only.

#### Deliverables

- `tests/test_roundtrip.py`

#### Dependencies

- Task 3-3
- Task 2-2

#### Implementation Notes

- Cover public-API roundtrip for:
  - empty string
  - whitespace-only text
  - ASCII text
  - emoji
  - CJK
  - Arabic
  - mixed punctuation
  - one or more occurrences of `<|endoftext|>`
  - text containing `<|endoftext|>` surrounded by Unicode
  - partial special-token strings (`<|endoftext`, `endoftext|>`, `<|endo`) treated as ordinary text and roundtripping correctly
  - multiple consecutive special tokens (`<|endoftext|><|endoftext|>`)
- Cover public-API error cases:
  - `encode("") == []`
  - `decode([]) == ""`
  - unknown token ID raises `KeyError`
  - invalid UTF-8 byte sequence raises `UnicodeDecodeError`
  - `Tokenizer.train(corpus, vocab_size=255)` raises `ValueError`
- Add post-load parity:
  - train
  - save
  - load
  - verify identical encode outputs and roundtrip behavior after load

#### Acceptance Criteria

1. `decode(encode(text)) == text` for every required fixture class, including partial special-token strings and multiple consecutive special tokens.
2. Error cases raise the exact exception types specified in the PRD: `ValueError` for invalid `vocab_size`, `KeyError` for unknown token IDs, `UnicodeDecodeError` for invalid byte sequences.
3. Save/load preserves identical encode output for the same inputs.
4. `uv run pytest tests/test_roundtrip.py` exits `0`.

#### Owner

- Claude Code

### Phase 3 Exit Gate

- The public `Tokenizer` API exists and matches the PRD.
- All roundtrip fixtures pass.
- Save/load preserves identical encode behavior through the public API.

---

## Phase 4: CLI, Benchmarks, Documentation, and Release Gate

**Goal:** Ship the user-facing CLI, benchmark evidence, and a clean-clone reviewer experience with no follow-up clarification.

### Task 4-1: Implement CLI Contract for `train`, `encode`, and `decode`

#### Objective

Implement the required CLI subcommands with strict stdout/stderr separation and machine-readable output.

#### Deliverables

- `src/bpetite/_cli.py`

#### Dependencies

- Phase 3 exit gate

#### Implementation Notes

- Use stdlib `argparse`.
- Implement subcommands:
  - `train`
  - `encode`
  - `decode`
- `train` arguments:
  - `--input`
  - `--vocab-size`
  - `--output`
  - `--force`
- `encode` arguments:
  - `--model`
  - `--text`
- `decode` arguments:
  - `--model`
  - `--ids`
- `--force` maps to `overwrite=True` on the persistence layer's save call.
- `--ids` accepts one or more space-separated integers (`nargs="+"`, `type=int`).
- `--vocab-size` is a required argument with no default value.
- `train` must read input with UTF-8 strict decoding and fail fast on invalid UTF-8.
- The CLI `train` subcommand requires progress reporting during merge training. Because the public `Tokenizer.train(corpus, vocab_size)` API does not accept a progress callback, the CLI must call the internal `_trainer` module directly with a callback, then construct the `Tokenizer` instance from the training results. This is permitted because `_cli.py` is itself an internal module.
- `train` must write progress updates to `stderr`:
  - start
  - every 100 merges completed
  - completion
- `train` must write a machine-readable JSON object to `stdout` with exactly these fields:
  - `corpus_bytes`
  - `requested_vocab_size`
  - `actual_mergeable_vocab_size`
  - `special_token_count`
  - `elapsed_ms`
- `encode` must write a compact JSON array to `stdout` using fixed compact separators.
- `decode` must write raw decoded text to `stdout` with no wrapper text.
- Known runtime failures must exit non-zero and print human-readable messages to `stderr` only.
- `argparse` argument errors may use the standard exit code `2`.

#### Acceptance Criteria

1. `train` writes progress updates only to `stderr`.
2. `train` writes a machine-readable JSON summary only to `stdout`.
3. `encode` writes a compact JSON array only to `stdout`.
4. `decode` writes raw decoded text only to `stdout`.
5. Missing files, invalid UTF-8 input files, unknown token IDs, and invalid decoded bytes fail non-zero and write only to `stderr`.

#### Owner

- Claude Code

### Task 4-2: Add CLI Contract Tests

#### Objective

Verify the CLI through subprocess-level tests, including output-channel separation and file-read failure modes.

#### Deliverables

- `tests/test_cli.py`

#### Dependencies

- Task 4-1
- Task 2-2

#### Implementation Notes

- Invoke the installed console entry point with subprocesses.
- Cover:
  - successful `train`
  - successful `encode`
  - successful `decode`
  - nonexistent input file
  - invalid UTF-8 input file using `invalid_utf8.bin`
  - save without `--force` to an existing output path
  - save with `--force`
  - unknown decode ID
  - invalid decoded bytes
  - progress on `stderr`
  - JSON summary on `stdout`
  - compact JSON array formatting for `encode`
- Assert that normal machine-readable results do not leak onto `stderr` and that errors do not leak onto `stdout`.

#### Acceptance Criteria

1. CLI tests cover all required runtime and channel-separation cases.
2. `uv run pytest tests/test_cli.py` exits `0`.
3. CLI tests pass on both supported CI OS targets.

#### Owner

- Claude Code

### Task 4-3: Add the TinyShakespeare Download Helper

#### Objective

Provide a single local helper for obtaining the demo corpus without introducing runtime network behavior.

#### Deliverables

- `scripts/download_corpus.py`

#### Dependencies

- Task 1-1

#### Implementation Notes

- Use `urllib.request` from the standard library.
- Download URL: `https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt`
- Destination: `data/tinyshakespeare.txt`.
- Keep the script outside the core package path.
- Ensure `.gitignore` covers the downloaded corpus.

#### Acceptance Criteria

1. `python scripts/download_corpus.py` downloads the corpus to `data/tinyshakespeare.txt`.
2. The downloaded corpus is not committed.
3. The script is not imported by the core library or CLI runtime path.

#### Owner

- Claude Code

### Task 4-4: Add the Benchmark Harness and Record Manual Demo Results

#### Objective

Generate the benchmark evidence required by the PRD and record the actual results on the benchmark machine.

#### Deliverables

- `scripts/bench_encode.py`
- `docs/benchmarks.md`

#### Dependencies

- Task 4-1
- Task 4-3

#### Implementation Notes

- `bench_encode.py` must:
  - load a saved tokenizer
  - encode a fixed 50-word sentence 100 times
  - record elapsed times with `time.perf_counter()`
  - report:
    - `p50` using median
    - `p99` using nearest-rank on the sorted samples
- Run and document:
  - TinyShakespeare training at `vocab_size=512`
  - the 50-word encode benchmark over 100 runs
  - demo-only training at `vocab_size=32000`
- `docs/benchmarks.md` must record:
  - machine spec
  - Python version
  - OS
  - `512` training time
  - encode `p50`
  - encode `p99`
  - `32000` completion status and time

#### Acceptance Criteria

1. The benchmark script runs successfully against a saved tokenizer.
2. `docs/benchmarks.md` contains all required machine and timing data.
3. `vocab_size=512` training is documented with the actual elapsed time.
4. `vocab_size=32000` completion is manually verified and documented, even though it is not CI-gated.

#### Owner

- Human engineer

### Task 4-5: Write the Final README

#### Objective

Write a README that lets a first-time reviewer set up the repo, run the CLI, and understand the project limits without opening the PRD.

#### Deliverables

- `README.md`

#### Dependencies

- Task 4-1
- Task 4-4

#### Implementation Notes

- Required sections:
  - project description
  - local setup with locked sync
  - corpus download
  - CLI examples for `train`, `encode`, and `decode`
  - testing commands
  - limits and non-goals
  - benchmark summary with a link to `docs/benchmarks.md`
- The README must explicitly state:
  - not a production tokenizer
  - no exact GPT-2 or `tiktoken` parity guarantee
  - Windows not supported
  - no PyPI publication in v1
- Use the exact CLI syntax that exists in code, not draft syntax copied from planning text.

#### Acceptance Criteria

1. Every CLI example in the README runs as written.
2. Setup instructions use locked dependency installation.
3. Limits and non-goals match the PRD exactly.
4. Benchmark numbers match `docs/benchmarks.md`.

#### Owner

- Human engineer + Claude Code

### Task 4-6: Run the Final Release Gate

#### Objective

Perform the final end-to-end handoff validation before declaring v1 launch-ready.

#### Deliverables

- Final validation evidence in the PR or handoff notes

#### Dependencies

- Task 4-2
- Task 4-5

#### Implementation Notes

- Validate from a clean clone on a supported machine:
  - `uv sync --locked`
  - `uv run pytest`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run mypy --strict`
  - README setup steps
  - README CLI examples
- Confirm:
  - no follow-up clarification is needed for a first-time reviewer
  - CLI output channels match the PRD
  - benchmark documentation exists
  - generated artifacts remain untracked

#### Acceptance Criteria

1. All FR-36 commands pass from a clean clone.
2. README steps work as written from a clean clone.
3. The CLI is usable end-to-end without reading any other file.
4. No generated corpus or tokenizer artifact is accidentally tracked.

#### Owner

- Human engineer

### Phase 4 Exit Gate

- CLI contract tests are green.
- Benchmarks are documented.
- README is accurate.
- Clean-clone validation passes with no follow-up questions.

---

## Phase 5: Optional Reference Comparison

**Goal:** Add the optional `compare-tiktoken` reference command only after launch-critical work is complete.

### Task 5-1: Implement Optional `compare-tiktoken`

#### Objective

Add the informational-only reference comparison command without changing launch-critical correctness requirements.

#### Deliverables

- updated `src/bpetite/_cli.py`
- optional `tests/test_compare_tiktoken.py`
- README update for the optional command

#### Dependencies

- Phase 4 exit gate

#### Implementation Notes

- Add the `compare-tiktoken` subcommand.
- Use `tiktoken.get_encoding("gpt2")`.
- Guard the import cleanly and exit non-zero with a helpful message if `tiktoken` is unavailable.
- Output:
  - `bpetite` token IDs
  - `bpetite` token count
  - `tiktoken` token IDs
  - `tiktoken` token count
  - a note that parity is not expected
- This task is optional and is not a launch blocker for v1.

#### Acceptance Criteria

1. The command works when `tiktoken` is installed.
2. The command fails cleanly with a helpful error when `tiktoken` is unavailable.
3. Output explicitly states that exact parity is not expected.
4. If a smoke test is added, it passes in the dev environment.

#### Owner

- Claude Code

---

## Recommended Execution Order

1. ~~`1-1` Repo scaffold and ignore policy~~
2. ~~`1-2` `pyproject.toml` and tool configuration~~
3. ~~`1-3` Lockfile and editable install~~
4. ~~`1-4` Hardened CI~~
5. `2-1` Shared constants and contracts
6. `2-2` Deterministic fixtures
7. `2-3` Pre-tokenizer implementation
8. `2-4` Pre-tokenizer tests
9. `2-5` Trainer implementation
10. `2-6` Trainer tests
11. `2-7` Persistence implementation
12. `2-8` Persistence tests and determinism gate
13. `3-1` Encoder implementation
14. `3-2` Decoder implementation
15. `3-3` Public `Tokenizer` API
16. `3-4` Roundtrip and public API tests
17. `4-1` CLI implementation
18. `4-2` CLI contract tests
19. `4-3` Corpus download helper
20. `4-4` Benchmark harness and manual demo
21. `4-5` README
22. `4-6` Final release gate
23. `5-1` Optional `compare-tiktoken`

## Parallelization Opportunities

- After `2-3`, `2-4` and `2-5` can proceed in parallel.
- After `2-5`, `2-6` and `2-7` can proceed in parallel.
- After Phase 2, `3-1` and `3-2` can proceed in parallel.
- After `4-1`, `4-2` and `4-3` can proceed in parallel.

## Human-Required Tasks

- ~~`1-3` Generate the initial lockfile in the local environment.~~
- ~~`1-4` Verify the GitHub Actions workflow on the remote repository.~~
- `4-4` Run and record benchmark results on the benchmark machine.
- `4-5` Validate README commands on a clean machine.
- `4-6` Perform the final clean-clone release gate.

## Open Questions

None.
