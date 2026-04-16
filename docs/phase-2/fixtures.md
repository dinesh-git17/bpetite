---
title: Test Fixtures
description: Purpose, byte invariants, whitespace-preservation rule, and conftest fixture surface for the bpetite test suite.
slug: phase-2-fixtures
order: 13
category: Phase 2
published: true
---

# Test Fixtures: deterministic inputs for a reproducible test suite

## TL;DR

- Four fixture files in `tests/fixtures/` provide controlled, byte-exact inputs; every
  content invariant is a repo-wide constraint, not just a test assumption.
- `unicode.txt` uses U+3000 IDEOGRAPHIC SPACE on its whitespace-only line because the
  pre-commit hook strips trailing ASCII whitespace. Non-ASCII codepoints survive unmodified.
- The `tiny_corpus` → `trained_state` chain is the backbone of the persistence test suite:
  `tiny.txt` is fixed, the trainer is deterministic, so `trained_state` is byte-identical
  across every test session.

## What lives here

| File                              | Bytes | Purpose                                                                                                                                                    |
| --------------------------------- | ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/fixtures/tiny.txt`         | 212   | Deterministic training target; pangrams repeated five times, ASCII-only, supports up to 44 merges at `vocab_size=300` without early-stopping               |
| `tests/fixtures/unicode.txt`      | 115   | Multi-script coverage: emoji, CJK, Arabic, a whitespace-only line (U+3000), the `<\|endoftext\|>` literal, and mixed-script text                           |
| `tests/fixtures/empty.txt`        | 0     | Exactly zero bytes; exercises the empty-corpus early-stop path in the trainer (FR-11)                                                                      |
| `tests/fixtures/invalid_utf8.bin` | 4     | Bytes `\xff\xfe\xfd\x0a`: the first byte (`0xff`) is an invalid UTF-8 start byte; reading with `encoding="utf-8"` raises `UnicodeDecodeError` immediately |
| `tests/conftest.py`               | n/a   | Session-scoped pytest fixtures that surface the four files to the test suite                                                                              |

## Key invariants

| Fixture              | Invariant                                                                        | Consequence if violated                                                                                                                                                              |
| -------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `empty.txt`          | Exactly 0 bytes, not one byte and not a newline                                  | A 1-byte file (e.g. containing `\n`) does not test the truly empty path; `empty_corpus` would be `"\n"` and the trainer would pre-tokenize it to a non-empty chunk list              |
| `invalid_utf8.bin`   | Exactly 4 bytes; first byte is `0xff`                                            | A shorter file might not survive binary git operations; a valid UTF-8 prefix would not trigger `UnicodeDecodeError` at byte 0                                                        |
| `unicode.txt` line 4 | Whitespace-only line uses U+3000 (IDEOGRAPHIC SPACE), not ASCII spaces or tabs   | The pre-commit trailing-whitespace hook strips ASCII whitespace; a line of regular spaces would be silently modified, changing the file's byte content and breaking byte-determinism |
| `tiny.txt`           | Content is fixed and ASCII-only; supports at least 44 merges at `vocab_size=300` | Changing the content changes `trained_state`, invalidating every byte-equality assertion in `tests/test_persistence.py`                                                              |

## Walkthrough

### Fixture files in detail

**`tests/fixtures/tiny.txt`** (212 bytes)

Five pangrams repeated across five lines (three repetitions of the first pangram, two of the
second), followed by a trailing newline. The content is entirely ASCII, so every byte maps
one-to-one to a base-byte token. The repetition creates enough pair frequency for the trainer
to find 44 distinct merges at `vocab_size=300` without early-stopping. This makes `tiny.txt`
the reliable training target for session-scoped fixtures.

**`tests/fixtures/unicode.txt`** (115 bytes)

Six lines covering the Unicode edge cases that the trainer and encoder must handle:

1. `Hello 🙂 world 🎉`: emoji (multi-byte UTF-8 sequences)
2. `你好世界`: CJK characters
3. `مرحبا بالعالم`: Arabic script
4. `　　　`: three IDEOGRAPHIC SPACE codepoints (U+3000), the whitespace-only line
5. `<|endoftext|>`: the reserved special-token literal as ordinary training text
6. `mixed: 你好 🌍 مرحبا`: multiple scripts on one line

Line 5 matters for FR-15 coverage: the trainer must not pre-extract the literal, so
it must flow through pre-tokenization and pair counting as ordinary bytes.

**`tests/fixtures/empty.txt`** (0 bytes)

The file contains no bytes at all. `empty_corpus` resolves to the Python string `""`.
`train_bpe("", vocab_size)` produces zero pre-tokens and therefore zero pairs; the merge
loop exits immediately at the first iteration without performing any merges (FR-11). The
special token is still reserved at ID 256.

The invariant is strict: the file must be exactly 0 bytes, not "effectively empty." A file
containing only a newline (`\x0a`) would produce `tiny_corpus = "\n"`, which pre-tokenizes
to `[b"\n"]`, a non-empty chunk. That single-element list has no adjacent pairs, so the
trainer still early-stops, but the semantic is subtly different from a truly empty corpus
and would give a false pass to any test that checks for the empty-input path specifically.

**`tests/fixtures/invalid_utf8.bin`** (4 bytes: `\xff\xfe\xfd\x0a`)

The bytes `\xff` and `\xfe` are the UTF-16 little-endian BOM. Neither is a valid UTF-8
start byte: `\xff` is always invalid in UTF-8; `\xfe` is likewise invalid. Python's UTF-8
codec raises `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0:
invalid start byte` before examining any subsequent bytes.

This file is used exclusively in CLI file-read tests (Phase 4, `tests/test_cli.py`). It is
never passed to the library-level `train_bpe`, `save`, or `load` functions because those
accept `str` and `str` paths respectively. The CLI is the only entry point that reads raw
bytes from disk and must handle the decoding failure at the boundary.

### The whitespace-preservation rule

The repo uses a pre-commit hook that strips trailing ASCII whitespace from text files.
A whitespace-only line composed of regular ASCII spaces (`\x20`) or tabs (`\x09`) would be
reduced to an empty line by the hook, changing `unicode.txt`'s byte content without
triggering a git conflict.

Line 4 of `unicode.txt` uses three U+3000 IDEOGRAPHIC SPACE codepoints (`\xe3\x80\x80` each
in UTF-8). The hook targets only ASCII whitespace code points; U+3000 is outside that range
and is left intact. The line is preserved byte-for-byte across commits.

Any future edit to `unicode.txt` that adds a whitespace-only line must use a non-ASCII
Unicode whitespace codepoint (U+3000 or U+00A0 NO-BREAK SPACE) for the same reason.

### The `tiny.txt` to `trained_state` reproducibility chain

The session-scoped `trained_state` fixture in `tests/test_persistence.py` is the foundation
of the persistence test suite. Its reproducibility rests on three links:

```
tests/fixtures/tiny.txt     (fixed content, committed to repo)
         |
         v
tiny_corpus fixture          (session-scoped; reads tiny.txt once per pytest session)
         |
         v
train_bpe(tiny_corpus, 300)  (deterministic per FR-12; same output every run)
         |
         v
trained_state fixture        (session-scoped TrainerResult; constant across sessions)
         |
         v
test_same_state_saved_twice_produces_identical_bytes
test_repeated_training_then_saving_produces_identical_artifacts
         (byte-equality assertions; any change in the chain breaks these)
```

If `tiny.txt` is modified, `trained_state` changes. If the trainer is made nondeterministic,
`trained_state` changes between sessions. Either way, the byte-equality assertions in
`tests/test_persistence.py` fail, surfacing the regression. The chain is self-enforcing.

### The conftest fixture surface

`tests/conftest.py` exposes four session-scoped fixtures:

| Fixture             | Type           | Source                                                 |
| ------------------- | -------------- | ------------------------------------------------------ |
| `tiny_corpus`       | `str`          | `tests/fixtures/tiny.txt` read as UTF-8                |
| `unicode_corpus`    | `str`          | `tests/fixtures/unicode.txt` read as UTF-8             |
| `empty_corpus`      | `str`          | `tests/fixtures/empty.txt` read as UTF-8 (always `""`) |
| `invalid_utf8_path` | `pathlib.Path` | Path object only; content is not decoded               |

`invalid_utf8_path` returns a `Path`, not a string, because the file cannot be decoded as
UTF-8. Tests that use it pass the path to whatever CLI or file-reading code is under test
and assert the resulting error; they never call `.read_text()` on it directly.

A fifth session-scoped fixture, `trained_state`, is defined in `tests/test_persistence.py`
rather than `conftest.py` because it is consumed only by the persistence test module. Keeping
it local to that module avoids exposing a heavyweight fixture to unrelated tests.

### Pytest configuration

Three lines in `pyproject.toml` govern test collection behavior:

```toml
[tool.pytest.ini_options]
addopts = "--import-mode=importlib"
testpaths = ["tests"]
```

`--import-mode=importlib` enables importing from the installed `src/bpetite/` package without
a `tests/__init__.py` file and without `sys.path` manipulation. Tests import from the package
directly; there is no `tests/__init__.py` and none should be added.

## Failure modes

| Failure                                                 | Effect                                                                                    | Fixture affected    |
| ------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ------------------- |
| `empty.txt` contains a newline                          | `empty_corpus` is `"\n"` not `""`; empty-corpus trainer tests pass for the wrong reason   | `empty_corpus`      |
| Whitespace-only line in `unicode.txt` uses ASCII spaces | Pre-commit hook silently strips it; `unicode.txt` byte content changes across commits     | `unicode_corpus`    |
| `tiny.txt` content modified                             | `trained_state` changes; all byte-equality assertions in `tests/test_persistence.py` fail | `trained_state`     |
| `invalid_utf8.bin` replaced with valid UTF-8            | CLI file-read tests pass without exercising the `UnicodeDecodeError` path                 | `invalid_utf8_path` |
| `tests/__init__.py` added                               | `importlib` import mode breaks; test collection fails or imports wrong module             | all                 |

## Related reading

- [`docs/phase-2/index.md`](index.md): Phase 2 scope and reading order
- [`docs/phase-2/core-algorithm.md`](core-algorithm.md): trainer behavior that `tiny_corpus`
  and `unicode_corpus` exercise
- [`docs/phase-2/persistence.md`](persistence.md): `trained_state` fixture and the
  determinism gates it anchors
- [`docs/bpetite-prd-v2.md`](../bpetite-prd-v2.md): FR-11 (early stop), FR-12
  (determinism), FR-15 (special-token handling during training)
- [`tests/conftest.py`](../../tests/conftest.py): fixture definitions
- [`tests/fixtures/`](../../tests/fixtures/): fixture files
