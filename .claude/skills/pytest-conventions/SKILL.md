---
name: pytest-conventions
description: "Encodes bpetite's mandatory pytest conventions. Use this skill whenever writing, editing, or reviewing any file in tests/ — including new test files, additions to existing test files, conftest.py, or test fixture work. Also trigger on: write a test, add a test, test suite, pytest, fixture, roundtrip test, parametrize, tmp_path, encode test, decode test, UnicodeDecodeError test, or any request to cover a new code path in the bpetite package with tests. Do not wait for an explicit use pytest-conventions instruction — if the task touches tests/, load this skill automatically."
---

# bpetite pytest conventions

This skill encodes the non-negotiable testing conventions for the `bpetite`
project. Apply every rule here whenever writing or editing any file under
`tests/`. These conventions exist because the test suite is a portfolio artifact
that senior reviewers will read — consistency and intentionality matter as much
as correctness.

---

## 1. Project-level constraints (never violate these)

- `tests/__init__.py` must **not** exist. The project uses `importlib` import
  mode; a package init in the test directory breaks that.
- pytest is configured with `--import-mode=importlib` in `pyproject.toml`.
  Never rely on `sys.path` mutation or `PYTHONPATH` hacks to import test code.
- All test imports resolve against the **installed package** via `uv run pytest`,
  not against the repo root. If a test needs `bpetite`, it comes from the
  installed editable install — not from a relative path.

---

## 2. Parametrize multi-input tests — no one-function-per-input

Whenever a test exercises the same assertion logic against multiple inputs,
use `@pytest.mark.parametrize`. Never write a separate test function for each
input string.

**Correct pattern:**

```python
import pytest
from bpetite import Tokenizer

ROUNDTRIP_CASES = [
    ("empty string", ""),
    ("whitespace only", "   \n\t  "),
    ("ascii", "Hello, world!"),
    ("emoji", "🎉 party time 🎉"),
    ("cjk", "你好世界"),
    ("arabic", "مرحبا بالعالم"),
    ("mixed punctuation", "...wait—what?!"),
    ("single special token", "<|endoftext|>"),
    ("special token surrounded by unicode", "前 <|endoftext|> 後"),
    ("consecutive special tokens", "<|endoftext|><|endoftext|>"),
]

@pytest.mark.parametrize("label,text", ROUNDTRIP_CASES)
def test_roundtrip(trained_tokenizer: Tokenizer, label: str, text: str) -> None:
    assert trained_tokenizer.decode(trained_tokenizer.encode(text)) == text
```

**Why:** A flat list of `test_roundtrip_empty`, `test_roundtrip_whitespace`, …
is verbose, harder to extend, and signals a junior testing pattern. Parametrize
makes the intent explicit and keeps test IDs readable in CI output via the
`label` parameter.

**Name the parameter pair meaningfully.** The first element should be a
human-readable label that appears in the pytest node ID. Keep it short.

---

## 3. `tmp_path` for all file I/O — no hardcoded paths

Any test that writes a file (tokenizer artifacts, CLI output, temporary
corpora) must use pytest's built-in `tmp_path` fixture. Never write to `/tmp/`,
to a hardcoded path in the repo, or to `os.getcwd()`.

**Correct pattern:**

```python
def test_save_and_load(trained_tokenizer: Tokenizer, tmp_path: Path) -> None:
    artifact = tmp_path / "tokenizer.json"
    trained_tokenizer.save(str(artifact))
    loaded = Tokenizer.load(str(artifact))
    assert loaded.encode("hello") == trained_tokenizer.encode("hello")
```

**CLI subprocess tests also use `tmp_path`:**

```python
def test_cli_train(tmp_path: Path, tiny_corpus_path: Path) -> None:
    output = tmp_path / "tok.json"
    result = subprocess.run(
        ["uv", "run", "bpetite", "train",
         "--input", str(tiny_corpus_path),
         "--vocab-size", "260",
         "--output", str(output)],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert output.exists()
```

**Why:** `tmp_path` is pytest-managed, isolated per test, and cleaned up
automatically. Hardcoded paths cause flaky tests when the working directory
changes, and committed artifacts accidentally polluting the repo.

---

## 4. Internal module imports are acceptable

Tests for Phase 2 tasks (trainer, pre-tokenizer, persistence) import internal
modules directly. This is intentional — these tests exist to verify the
internals before the public API is wired. Do not limit tests to `from bpetite
import Tokenizer` when you need to test a specific internal function.

**Acceptable internal imports:**

```python
from bpetite._pretokenizer import pretokenize
from bpetite._trainer import train_bpe   # or whatever the internal entry point is
from bpetite._persistence import save_artifact, load_artifact
from bpetite._encoder import encode
from bpetite._decoder import decode
```

**Rule:** Internal imports are fine in `test_pretokenizer.py`,
`test_trainer.py`, and `test_persistence.py`. Use only the public
`Tokenizer` API in `test_roundtrip.py` and `test_cli.py` — those tests
prove the public contract, not the internals.

---

## 5. conftest.py corpus fixtures

Shared fixtures live in `tests/conftest.py`. Do not redefine corpus loading
inside individual test files.

**Canonical conftest structure:**

```python
# tests/conftest.py
from __future__ import annotations

import pytest
from pathlib import Path
from bpetite import Tokenizer

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def tiny_corpus() -> str:
    return (FIXTURES / "tiny.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def unicode_corpus() -> str:
    return (FIXTURES / "unicode.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def empty_corpus() -> str:
    return (FIXTURES / "empty.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def invalid_utf8_path() -> Path:
    return FIXTURES / "invalid_utf8.bin"


@pytest.fixture(scope="session")
def tiny_corpus_path() -> Path:
    return FIXTURES / "tiny.txt"


@pytest.fixture(scope="session")
def trained_tokenizer(tiny_corpus: str) -> Tokenizer:
    return Tokenizer.train(tiny_corpus, vocab_size=260)
```

**Conventions:**

- Use `scope="session"` for fixtures that are expensive to construct (training
  a tokenizer, reading corpora). Use `scope="function"` (the default) only when
  the fixture must be isolated per test, such as mutable state or `tmp_path`
  dependents.
- `tiny_corpus_path` is a separate fixture from `tiny_corpus` because CLI
  subprocess tests need the actual file path, not the string content.
- Never call `Tokenizer.train` inside a test function body when the same
  trained tokenizer can be shared via a session-scoped fixture.

---

## 6. Roundtrip assertion pattern

The canonical roundtrip test is always written as a parametrized test using the
`trained_tokenizer` session fixture and the `ROUNDTRIP_CASES` list. See
Section 2 for the full example.

**Required input classes** (task list FR-25 / task 3-4):

- empty string `""`
- whitespace-only text
- ASCII text
- emoji
- CJK
- Arabic
- mixed punctuation
- text containing exactly one `<|endoftext|>`
- text containing consecutive `<|endoftext|><|endoftext|>`
- text with `<|endoftext|>` surrounded by Unicode characters

Every class must appear as a distinct parametrize case. Do not collapse them.

**The assertion is always:**

```python
assert tokenizer.decode(tokenizer.encode(text)) == text
```

Never assert token IDs directly in the roundtrip test — that makes the test
brittle to merge-order changes. Assert only the string identity.

---

## 7. UnicodeDecodeError test path

Testing `UnicodeDecodeError` requires producing a sequence of token IDs whose
concatenated bytes form an invalid UTF-8 byte sequence. Do **not** try to find
a single token ID whose bytes are invalid — base tokens 0–255 are individually
valid byte values. The trick is to concatenate byte tokens that together form
an incomplete or overlong UTF-8 sequence.

**Canonical approach:**

```python
def test_decode_invalid_utf8_raises(trained_tokenizer: Tokenizer) -> None:
    # 0x80 is a UTF-8 continuation byte with no preceding start byte.
    # Passing [128] produces b'\x80', which is invalid UTF-8 on its own.
    with pytest.raises(UnicodeDecodeError):
        trained_tokenizer.decode([128])
```

**Why this works:** Token ID 128 maps to the single byte `b'\x80'`. A lone
continuation byte (0x80–0xBF) without a preceding multi-byte start byte
(0xC2–0xFD) is always invalid UTF-8 under strict decoding. This is
deterministic regardless of merge training — byte 128 is always in the base
vocabulary.

**Alternative for a more complex sequence:**

```python
def test_decode_truncated_multibyte_raises(trained_tokenizer: Tokenizer) -> None:
    # 0xE2 starts a 3-byte UTF-8 sequence; without the two following
    # continuation bytes it is invalid.
    with pytest.raises(UnicodeDecodeError):
        trained_tokenizer.decode([0xE2])  # token ID 226
```

Both patterns are valid. Use at least one. Document why the byte value was
chosen inline so a reviewer understands the construction.

---

## 8. Error-case test patterns

**`KeyError` for unknown token IDs:**

```python
def test_decode_unknown_id_raises(trained_tokenizer: Tokenizer) -> None:
    unknown_id = 999_999
    with pytest.raises(KeyError):
        trained_tokenizer.decode([unknown_id])
```

**`ValueError` for `vocab_size < 256`:**

```python
@pytest.mark.parametrize("bad_size", [0, 1, 100, 255])
def test_train_small_vocab_raises(tiny_corpus: str, bad_size: int) -> None:
    with pytest.raises(ValueError):
        Tokenizer.train(tiny_corpus, bad_size)
```

Parametrize error cases too when there are multiple representative inputs.

---

## 9. CLI test structure

CLI tests use `subprocess.run` against the installed console entry point.
Always capture both streams and assert them separately.

```python
def test_cli_encode_stdout_only(trained_artifact: Path) -> None:
    result = subprocess.run(
        ["uv", "run", "bpetite", "encode",
         "--model", str(trained_artifact),
         "--text", "Hello"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stderr == ""          # nothing leaks to stderr on success
    ids = json.loads(result.stdout)
    assert isinstance(ids, list)
    assert all(isinstance(i, int) for i in ids)
```

**Channel-separation assertions are mandatory** in CLI tests:

- On success: assert `stderr == ""` and `stdout` contains the expected payload.
- On failure: assert `returncode != 0` and `stdout == ""` and `stderr` is non-empty.

Never only check `returncode`. The PRD requires strict stdout/stderr separation
(FR-33, FR-34); CLI tests must prove it.

---

## 10. What not to do — common violations to avoid

| Anti-pattern                                               | Correct alternative                                         |
| ---------------------------------------------------------- | ----------------------------------------------------------- |
| One test function per input string                         | `@pytest.mark.parametrize`                                  |
| `open("/tmp/tok.json", "w")` in tests                      | `tmp_path / "tok.json"`                                     |
| `sys.path.insert(0, "src")` anywhere in tests              | Rely on editable install via `uv run pytest`                |
| `tests/__init__.py` exists                                 | Delete it; importlib mode makes it unnecessary and harmful  |
| Asserting specific token IDs in roundtrip tests            | Assert `decode(encode(text)) == text` only                  |
| Constructing `UnicodeDecodeError` with string manipulation | Construct with raw byte ID values from base vocabulary      |
| `Tokenizer.train(corpus, 260)` inside every test function  | Session-scoped `trained_tokenizer` fixture in conftest      |
| Importing `bpetite._tokenizer.Tokenizer`                   | Import `from bpetite import Tokenizer` for public API tests |
