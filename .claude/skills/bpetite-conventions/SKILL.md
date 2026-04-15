---
name: bpetite-conventions
description: Foundational project conventions for the bpetite tokenizer library. Encodes the src/ package layout, underscore-prefix internal module rules, the only-Tokenizer export contract, every correct uv command for every operation, the full module-to-task ownership map, and the mandatory four-command quality gate that must pass before any task is declared done. Load this skill before touching any .py file, writing any test, implementing any module, or starting any task from the task list. Always invoke when the user says "implement", "create module", "add test", "write", "start task", references any task ID (1-x through 5-x), or when Claude Code is about to read or edit any .py file in this project. Do not write code in this project without consulting this skill first.
---

# bpetite Project Conventions

This skill is the single source of truth for structural conventions in the `bpetite` project. Read it before writing any code, any test, or any configuration file.

---

## Quality Gate — Mandatory Before Declaring Any Task Done

Run all four commands. All four must be green. A task is not done until this is true.

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict
```

**Green on tests + red on mypy = not done.**
**Green on mypy + failing format check = not done.**
All four must pass. No exceptions, no partial credit.

---

## Package Layout

The project uses a `src/` layout unconditionally.

```
bpetite/
├── src/
│   └── bpetite/
│       ├── __init__.py           ← exports ONLY `Tokenizer`; nothing else
│       ├── _cli.py               ← CLI entry point          [internal]
│       ├── _constants.py         ← shared constants         [internal]
│       ├── _decoder.py           ← decoding logic           [internal]
│       ├── _encoder.py           ← encoding logic           [internal]
│       ├── _persistence.py       ← save / load logic        [internal]
│       ├── _pretokenizer.py      ← GPT-2-style pre-tokenizer [internal]
│       ├── _tokenizer.py         ← public Tokenizer class   [internal]
│       └── _trainer.py           ← BPE training logic       [internal]
├── tests/
│   ├── conftest.py               ← shared pytest fixtures
│   ├── fixtures/
│   │   ├── empty.txt             ← exactly 0 bytes
│   │   ├── invalid_utf8.bin      ← bytes that fail strict UTF-8 decode
│   │   ├── tiny.txt              ← small deterministic training corpus
│   │   └── unicode.txt           ← emoji, CJK, Arabic, <|endoftext|>
│   ├── test_cli.py
│   ├── test_persistence.py
│   ├── test_pretokenizer.py
│   ├── test_roundtrip.py
│   └── test_trainer.py
├── data/                         ← gitignored; no committed corpora here
├── docs/
│   └── benchmarks.md
├── scripts/
│   ├── bench_encode.py
│   └── download_corpus.py
├── .github/
│   └── workflows/
│       └── ci.yml
├── pyproject.toml
├── uv.lock                       ← committed; use locked sync in CI
└── README.md
```

### Internal module naming

Every module under `src/bpetite/` except `__init__.py` uses a `_` prefix. These are internal. They carry no backward compatibility guarantee and must never be imported by test code directly — tests go through the public `Tokenizer` API or the installed package path.

### `__init__.py` export rule

`__init__.py` exports exactly one name:

```python
from bpetite._tokenizer import Tokenizer

__all__ = ["Tokenizer"]
```

Do not add convenience re-exports. Do not expose internal module names. `from bpetite import Tokenizer` is the only valid public import.

### Test structure rule

`tests/__init__.py` must not exist. Tests import via `importlib` mode from the installed `src/` package. Never mutate `sys.path` or `PYTHONPATH` to make tests work.

---

## uv Command Reference

| Operation             | Correct command                         |
| --------------------- | --------------------------------------- |
| Initial local setup   | `uv sync`                               |
| CI / locked setup     | `uv sync --locked`                      |
| Run tests             | `uv run pytest`                         |
| Lint                  | `uv run ruff check .`                   |
| Check formatting (CI) | `uv run ruff format --check .`          |
| Auto-format (local)   | `uv run ruff format .`                  |
| Type check            | `uv run mypy --strict`                  |
| Run CLI               | `uv run bpetite <subcommand>`           |
| Run a helper script   | `uv run python scripts/<name>.py`       |
| Collect tests only    | `uv run pytest --collect-only`          |
| Compile-check stubs   | `python -m py_compile src/bpetite/*.py` |

**Never use `pip install`, `python -m pytest`, or `python -m mypy`.** All tool invocations in this project go through `uv run`. The lockfile (`uv.lock`) is committed and must be used for all CI runs.

---

## Module Ownership Map

Each file is created (or primarily modified) by a specific task. Before editing a file, confirm which task owns it and whether that phase's exit gate is green.

| File                                                                | Owning task | Key deliverable                                                                                                               |
| ------------------------------------------------------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------- |
| All `src/bpetite/*.py` stubs                                        | **1-1**     | Valid stub bodies; `py_compile` must pass                                                                                     |
| `tests/fixtures/`, `data/`, `scripts/` dirs                         | **1-1**     | Directory structure only                                                                                                      |
| `.gitignore`                                                        | **1-1**     | Excludes venvs, caches, corpora, artifacts                                                                                    |
| `pyproject.toml`                                                    | **1-2**     | hatchling backend; `regex` runtime dep; `dev` group; console script; pytest importlib mode                                    |
| `uv.lock`                                                           | **1-3**     | Human task — generate with `uv sync`; verify `uv run python -c "import bpetite"` passes                                       |
| `.github/workflows/ci.yml`                                          | **1-4**     | Matrix: `ubuntu-latest` + `macos-latest`; Python 3.12; `uv sync --locked`; all four quality gates                             |
| `_constants.py`                                                     | **2-1**     | Canonical pre-tokenizer regex string; schema version `1`; special token literal `<\|endoftext\|>`                             |
| `tests/fixtures/*.txt`, `tests/fixtures/*.bin`, `tests/conftest.py` | **2-2**     | Deterministic fixture content; `empty.txt` is exactly 0 bytes                                                                 |
| `_pretokenizer.py`                                                  | **2-3**     | `pretokenize(text: str) -> list[bytes]`; uses `regex` package; compiled at module import time                                 |
| `tests/test_pretokenizer.py`                                        | **2-4**     | FR-4 to FR-6; byte-preserving concatenation asserted for every input                                                          |
| `_trainer.py`                                                       | **2-5**     | Deterministic BPE trainer; lexicographic tie-breaking; early-stop; progress callback; special token reservation               |
| `tests/test_trainer.py`                                             | **2-6**     | FR-7 to FR-15; chunk-boundary test uses crafted negative corpus, not heuristic scan                                           |
| `_persistence.py`                                                   | **2-7**     | Atomic save; validating load; duplicate-key rejection; strict shape and byte-range validation                                 |
| `tests/test_persistence.py`                                         | **2-8**     | Round-trip; overwrite guard; determinism gate (same state saved twice → identical bytes; trained twice → identical artifacts) |
| `_encoder.py`                                                       | **3-1**     | `encode(text, merges, special_tokens) -> list[int]`; exact special-token extraction before pre-tokenization                   |
| `_decoder.py`                                                       | **3-2**     | `decode(token_ids, vocab) -> str`; concatenate all bytes then decode once with UTF-8 strict                                   |
| `_tokenizer.py` + `__init__.py`                                     | **3-3**     | Public `Tokenizer` class; exactly five methods: `train`, `encode`, `decode`, `save`, `load`                                   |
| `tests/test_roundtrip.py`                                           | **3-4**     | `decode(encode(text)) == text` for all required fixture classes; post-load parity                                             |
| `_cli.py`                                                           | **4-1**     | `train`, `encode`, `decode` subcommands; strict stdout/stderr separation; progress on stderr                                  |
| `tests/test_cli.py`                                                 | **4-2**     | Subprocess-level contract tests; channel-separation assertions                                                                |
| `scripts/download_corpus.py`                                        | **4-3**     | Downloads TinyShakespeare via `urllib.request`; not imported by core runtime                                                  |
| `scripts/bench_encode.py` + `docs/benchmarks.md`                    | **4-4**     | Human task — run on benchmark machine; record p50 and p99 over 100 runs                                                       |
| `README.md`                                                         | **4-5**     | Human + Claude Code — all CLI examples must match actual code                                                                 |
| `_cli.py` (compare-tiktoken addition)                               | **5-1**     | Optional; do not start until Phase 4 exit gate is green                                                                       |

---

## Critical Invariants — Never Violate

### Algorithm pipeline

- No normalization, case folding, prefix-space insertion, or whitespace trimming anywhere in the pipeline. Not before pre-tokenization. Not after. Nowhere.
- `vocab_size` always means mergeable vocabulary size. It never counts reserved special tokens. This distinction matters everywhere: in the trainer, the persistence layer, and the CLI summary output.
- The only reserved special token in v1 is the exact string `<|endoftext|>`. No others.
- Core algorithm code must remain pure Python. No Rust bindings, no C extensions, no external tokenizer libraries in the implementation path.

### Dependencies

- `regex` and `rich` are the only runtime dependencies beyond the standard library. `regex` powers the pre-tokenizer; `rich` powers the CLI presentation layer (stderr-only) and does not touch the core algorithm or the public `Tokenizer` API.
- `tiktoken` is declared as a dev-only dependency. It must never appear in the core library or CLI runtime import path.

### Typing and bytes

- All byte-handling code must satisfy strict mypy semantics.
- Do not rely on implicit coercions between `bytes`, `bytearray`, and `memoryview`.

### Testing import paths

- Tests import from the installed package (`import bpetite`, `from bpetite import Tokenizer`).
- No `sys.path` mutations. No relative imports from `tests/` into `src/`.
- `tests/__init__.py` must not exist.
- `pytest` runs with `--import-mode=importlib` (configured in `pyproject.toml`; not passed manually).

### CLI output channels

- Machine-readable results (compact JSON arrays, JSON summaries, raw decoded text) go to `stdout` only.
- All progress updates and all human-readable error messages go to `stderr` only.
- No runtime network calls from the core library or CLI. The download helper script is the only networked code and it lives outside the core package.

### Persistence

- The artifact format is a single JSON file. Not multiple files. Not binary.
- Saves are atomic: write to a temp file in the destination directory, then `os.replace()` to the final path.
- The loader is data-only JSON parsing. It must never evaluate code or import modules from artifact content.
- Saving to an existing path without `overwrite=True` raises `FileExistsError`.
- Saving to a path with a missing parent raises `FileNotFoundError`.

### Platforms and CI

- Supported execution targets: macOS and Linux only. Windows is explicitly not supported.
- CI runs on `ubuntu-latest` and `macos-latest` with Python 3.12.
- CI uses `uv sync --locked`. Never float dependencies in CI.

### .gitignore — required exclusions

```
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
data/tinyshakespeare.txt
data/tinyshakespeare-*.json
```

Generated tokenizer artifacts and downloaded corpora must never be committed.

---

## Phase Exit Gates

Do not start a phase until the previous phase's exit gate is green.

| Phase   | Exit gate condition                                                                                                                         |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Phase 1 | Repo structure exists; lockfile committed; tests import via installed package path; CI green                                                |
| Phase 2 | Pre-tokenizer tests green; trainer tests green; persistence tests green; repeated training on same corpus produces byte-identical artifacts |
| Phase 3 | Public `Tokenizer` API exists and matches PRD; all roundtrip fixtures pass; save/load preserves identical encode behavior                   |
| Phase 4 | CLI contract tests green; benchmarks documented; README accurate; clean-clone validation passes                                             |
| Phase 5 | Optional; no exit gate required                                                                                                             |
