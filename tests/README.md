# Test Suite

192 tests, pure pytest, under two seconds on an M1.

The suite covers every load-bearing invariant in the PRD: pre-tokenizer
byte preservation, trainer tie-breaking and merge application, artifact
schema validation, public-API roundtrip fidelity, and CLI channel
separation. No mocks. No network calls. No database fixtures.

## Running

```bash
uv run pytest              # full suite
uv run pytest -q           # compact output
uv run pytest tests/test_trainer.py   # single module
```

The four quality gates that must pass before any commit:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict
```

## Test files

| File                   | Tests | What it covers                                                                                             |
| ---------------------- | ----: | ---------------------------------------------------------------------------------------------------------- |
| `test_pretokenizer.py` |    83 | GPT-2 regex pattern, byte preservation across ASCII/Unicode/CJK/emoji, contraction splits, whitespace runs |
| `test_roundtrip.py`    |    55 | `decode(encode(text)) == text` for every required input class via the public `Tokenizer` API               |
| `test_persistence.py`  |    22 | Artifact save/load fidelity, full loader validation checklist, two determinism proofs                      |
| `test_trainer.py`      |    19 | Pair counting, lexicographic tie-breaking, chunk boundary enforcement, early stop, progress callbacks      |
| `test_cli.py`          |    12 | Subprocess contract tests: stdout/stderr discipline, exit codes, error containment for train/encode/decode |
| `test_smoke.py`        |     1 | Package installs and resolves from the `src/` layout                                                       |

## Fixtures

Shared fixtures live in `conftest.py`. Corpus files live in `fixtures/`.

| Fixture file       | Bytes | Purpose                                                        |
| ------------------ | ----: | -------------------------------------------------------------- |
| `tiny.txt`         |   212 | Deterministic training corpus, small enough to pin merge order |
| `unicode.txt`      |   115 | Multi-script text: CJK, Arabic, emoji, mixed with ASCII        |
| `empty.txt`        |     0 | Edge case: zero-length corpus                                  |
| `invalid_utf8.bin` |     4 | Deliberately broken bytes for decoder error-path coverage      |

Session-scoped fixtures (`tiny_corpus`, `unicode_corpus`, `trained_tokenizer`)
keep training runs to exactly one per pytest invocation. CLI tests use
`tiny_corpus_path` for subprocess `--input` arguments because they need
the filesystem path, not the decoded string.

## Conventions

Tests follow the project's `pytest-conventions` skill. The short version:

- Test names describe the scenario:
  `test_train_tie_breaking_selects_lexicographically_smallest`, not
  `test_tiebreak`.
- `@pytest.mark.parametrize` for multi-input coverage. No duplicated
  functions for input variants.
- No `tests/__init__.py`. Import mode is `importlib`
  (set in `pyproject.toml`).
- Phase 2 tests import internal modules directly (`_trainer`, `_persistence`,
  `_pretokenizer`). Phase 3+ tests import only from the public `Tokenizer`
  API. The split is deliberate: internal tests pin mechanical contracts,
  public tests pin user-facing guarantees.
- Fixtures over setup/teardown. Keep them minimal, session-scoped where
  the cost justifies it.
- No mocks unless crossing an external service boundary. The only subprocess
  calls are in `test_cli.py`, which invokes the installed `bpetite` entry
  point to exercise the real CLI path.
