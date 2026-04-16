---
title: Roundtrip Suite
description: Parametrized cases, shared fixtures, and save/load parity design for the public-API roundtrip tests.
slug: phase-3-roundtrip-suite
order: 23
category: Phase 3
published: true
---

# Roundtrip Suite: 55 tests proving `decode(encode(text)) == text` through the public API

## TL;DR

- Fifty-five tests across seven functions in `tests/test_roundtrip.py` prove
  FR-17 through FR-26 through the public `Tokenizer` API only; no internal
  module is imported, and no token id is asserted directly.
- Fifteen parametrized cases cover every required input class: empty,
  whitespace, ASCII, emoji, CJK, Arabic, mixed punctuation, the literal
  `<|endoftext|>` in three configurations, and the three partial-special
  variants. The same list drives both the live-tokenizer run and the
  save/load parity run.
- Two shared fixtures keep the suite under 0.05 seconds: a session-scoped
  `trained_tokenizer` executes the training run exactly once per pytest
  invocation, and a module-scoped `saved_and_loaded_tokenizer` writes and
  reloads the artifact exactly once per test module.

## What lives here

| File                          | Purpose                                                                                                                                    |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `tests/test_roundtrip.py`     | 55-test public-API suite; seven test functions, four of them parametrized over the shared `ROUNDTRIP_CASES` list                           |
| `tests/conftest.py`           | Session-scoped `trained_tokenizer` fixture: `Tokenizer.train(tiny_corpus, vocab_size=260)`; constructed exactly once per pytest invocation |
| `tests/fixtures/tiny.txt`     | 212-byte ASCII training corpus (two pangrams × five lines); see [Phase 2 Fixtures](../phase-2/fixtures.md) for the byte invariants         |
| `src/bpetite/_tokenizer.py`   | The class under test; every assertion flows through its five public methods                                                                |
| `src/bpetite/_persistence.py` | The save/load layer exercised by the module-scoped `saved_and_loaded_tokenizer` fixture                                                    |

## Key invariants

| FR              | Invariant                                                                                                    | Consequence if violated                                                                                                   |
| --------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| FR-25           | `decode(encode(text)) == text` for every supported input class, asserted through the public `Tokenizer` API. | Any bug in the encoder, decoder, or special-token extraction corrupts inputs silently; the round-trip contract fails.     |
| FR-26           | Save/load preserves encode output byte-for-byte; a reloaded tokenizer is interchangeable with its source.    | A committed artifact decodes to different ids than the training-time tokenizer; deployments diverge from training.        |
| Task 3-4 design | This file imports only `from bpetite import Tokenizer`. Internal imports belong to Phase 2 tests, not here.  | Coupling the suite to internal APIs hides regressions in the public contract; breakages in `_tokenizer.py` pass silently. |
| Task 3-4 design | No test asserts specific token ids; only string identity after roundtrip.                                    | Brittle tests break on merge-order changes that are semantically equivalent; the suite becomes a maintenance tax.         |
| pytest config   | `tests/__init__.py` does not exist; pytest runs in `importlib` import mode.                                  | `importlib` import mode silently breaks and relative-path tricks sneak into the suite.                                    |

## Walkthrough

### The 15 parametrized cases

The `ROUNDTRIP_CASES` list in `tests/test_roundtrip.py:20` is shared across
three parametrized test functions: `test_roundtrip`, `test_post_load_encode_parity`,
and `test_post_load_roundtrip`. Adding a new input class means adding one
entry to this list, not writing a new test function.

| Case label                          | Input                                                                         | Proves                                         |
| ----------------------------------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `empty string`                      | `""`                                                                          | FR-17 / FR-21 roundtrip                        |
| `single space`                      | `" "`                                                                         | whitespace preserved                           |
| `whitespace only`                   | `"   \n\t  "`                                                                 | mixed whitespace preserved                     |
| `ascii sentence`                    | `"Hello, world!"`                                                             | ASCII + punctuation merges correctly           |
| `emoji`                             | `"\U0001f389 party time \U0001f38a"`                                          | 4-byte UTF-8 sequences preserved               |
| `cjk`                               | `"\u4f60\u597d\u4e16\u754c"`                                                  | 3-byte CJK preserved                           |
| `arabic`                            | `"\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645"` | RTL, 2-byte Arabic preserved                   |
| `mixed punctuation`                 | `"...wait\u2014what?!"`                                                       | em dash plus ASCII punctuation runs            |
| `single endoftext`                  | `"<\|endoftext\|>"`                                                           | FR-16 special extraction, FR-24 special decode |
| `multiple non-consecutive specials` | `"hello <\|endoftext\|> world <\|endoftext\|> again"`                         | multiple extraction points in one input        |
| `endoftext surrounded by unicode`   | `"\u524d <\|endoftext\|> \u5f8c"`                                             | extraction around multi-byte segments          |
| `consecutive specials`              | `"<\|endoftext\|><\|endoftext\|>"`                                            | FR-19 consecutive special ids in order         |
| `partial special prefix`            | `"<\|endoftext"`                                                              | FR-18 prefix flows through                     |
| `partial special suffix`            | `"endoftext\|>"`                                                              | FR-18 suffix flows through                     |
| `partial special short`             | `"<\|endo"`                                                                   | FR-18 short prefix flows through               |

### The seven test functions and what they prove

| Function                                         | Cases | Asserts                                                                                            |
| ------------------------------------------------ | ----- | -------------------------------------------------------------------------------------------------- |
| `test_roundtrip`                                 | 15    | `trained_tokenizer.decode(trained_tokenizer.encode(text)) == text` for every case                  |
| `test_encode_empty_returns_empty_list`           | 1     | `trained_tokenizer.encode("") == []` (FR-17 explicit)                                              |
| `test_decode_empty_returns_empty_string`         | 1     | `trained_tokenizer.decode([]) == ""` (FR-21 explicit)                                              |
| `test_decode_unknown_id_raises_key_error`        | 1     | `trained_tokenizer.decode([999_999])` raises `KeyError` (FR-22)                                    |
| `test_decode_invalid_utf8_raises`                | 1     | `trained_tokenizer.decode([0x80])` raises `UnicodeDecodeError` (FR-23)                             |
| `test_train_below_base_vocab_raises_value_error` | 5     | `Tokenizer.train(tiny_corpus, bad)` raises `ValueError` for `bad in [-1, 0, 1, 100, 255]` (FR-9)   |
| `test_post_load_encode_parity`                   | 15    | `saved_and_loaded_tokenizer.encode(text) == trained_tokenizer.encode(text)` for every case (FR-26) |
| `test_post_load_roundtrip`                       | 15    | Full roundtrip invariant holds through the save/load boundary for every case (FR-25 + FR-26)       |
| `test_save_and_load_returns_tokenizer_instance`  | 1     | `isinstance(Tokenizer.load(path), Tokenizer)` sanity check                                         |

Fifteen parametrized cases across three parametrized functions, plus ten
scalar tests, give 55 tests. That matches
`uv run pytest tests/test_roundtrip.py -v` → `55 passed`.

### The two shared fixtures

The suite trains a tokenizer exactly once per pytest invocation and
writes/reloads the artifact exactly once per test module, regardless of
how many cases use them. The session-scoped fixture lives in the shared
conftest so future Phase 3 or Phase 4 suites can reuse it; the
module-scoped fixture lives inside `test_roundtrip.py` because it is
local to this file's save/load parity design.

```python
# tests/conftest.py
@pytest.fixture(scope="session")
def trained_tokenizer(tiny_corpus: str) -> Tokenizer:
    return Tokenizer.train(tiny_corpus, vocab_size=260)
```

`vocab_size=260` yields up to 4 learned merges on top of the 256 base
bytes. That is enough to exercise the multi-rank encode path without
paying for a long training run; the tiny corpus early-stops before any
large merge table can form.

```python
# tests/test_roundtrip.py:48
@pytest.fixture(scope="module")
def saved_and_loaded_tokenizer(
    trained_tokenizer: Tokenizer,
    tmp_path_factory: pytest.TempPathFactory,
) -> Tokenizer:
    artifact_dir = tmp_path_factory.mktemp("roundtrip_artifact")
    artifact_path = artifact_dir / "tokenizer.json"
    trained_tokenizer.save(str(artifact_path))
    return Tokenizer.load(str(artifact_path))
```

Two details carry weight in this fixture. First, `tmp_path_factory` is
used instead of `tmp_path` because the fixture is module-scoped; pytest's
function-scoped `tmp_path` is not available in a module-scoped fixture.
Second, the artifact is written and reloaded exactly once, then the
resulting instance is reused across all thirty `test_post_load_*` cases.
Every parity assertion is therefore against the same loaded tokenizer,
so a save/load bug that flapped nondeterministically would fail all
thirty cases consistently rather than a random subset.

### The `[0x80]` UnicodeDecodeError construction

Testing FR-23 requires producing a sequence of token ids whose
concatenated bytes form an invalid UTF-8 sequence. The suite uses a
single base-byte id whose bytes are always invalid under strict UTF-8
decoding regardless of what merges were learned:

```python
def test_decode_invalid_utf8_raises(trained_tokenizer: Tokenizer) -> None:
    with pytest.raises(UnicodeDecodeError):
        trained_tokenizer.decode([0x80])
```

Token id `0x80` (decimal 128) resolves to the single byte `b"\x80"`. In
UTF-8, `0x80` is a continuation byte; it is only valid when immediately
preceded by a multi-byte lead byte (`0xC2`–`0xF4`). A lone continuation
byte is malformed, so `bytes.decode("utf-8", errors="strict")` raises
`UnicodeDecodeError: 'utf-8' codec can't decode byte 0x80 in position 0:
invalid start byte`.

The point of this construction is that it does not depend on any
particular training run. No merge learned from `tiny.txt` can mint a
token with these bytes, because the base vocab reserves id 128 for
`b"\x80"` and the training process never mints a new token id ≤ 255.
The assertion is stable across trainer implementations.

### Save/load parity design

The parity run does not write a new artifact per case. One artifact is
written by the module-scoped fixture at module setup time, then reloaded
exactly once. The resulting `saved_and_loaded_tokenizer` is compared
against the session-scoped `trained_tokenizer` via two independent
assertions per case:

```python
# tests/test_roundtrip.py:108
@pytest.mark.parametrize(("label", "text"), ROUNDTRIP_CASES)
def test_post_load_encode_parity(
    saved_and_loaded_tokenizer: Tokenizer,
    trained_tokenizer: Tokenizer,
    label: str,
    text: str,
) -> None:
    assert saved_and_loaded_tokenizer.encode(text) == trained_tokenizer.encode(text)

@pytest.mark.parametrize(("label", "text"), ROUNDTRIP_CASES)
def test_post_load_roundtrip(
    saved_and_loaded_tokenizer: Tokenizer, label: str, text: str
) -> None:
    assert (
        saved_and_loaded_tokenizer.decode(saved_and_loaded_tokenizer.encode(text))
        == text
    )
```

The `encode_parity` test is the strict one: it asserts that the two
tokenizers produce byte-identical id lists for the same input, not just
that both roundtrip. A save/load bug that perturbs merge order without
breaking the roundtrip invariant would pass `test_post_load_roundtrip`
but fail `test_post_load_encode_parity`.

## Failure modes

| Failure                                                                      | Exception type           | FR    | Caught by                                                                   |
| ---------------------------------------------------------------------------- | ------------------------ | ----- | --------------------------------------------------------------------------- |
| Any roundtrip case does not return the original string                       | `AssertionError`         | FR-25 | `test_roundtrip[<label>-...]` for the offending case                        |
| Save/load produces a tokenizer whose encode output differs from the source   | `AssertionError`         | FR-26 | `test_post_load_encode_parity[<label>-...]`                                 |
| `tests/__init__.py` is accidentally created                                  | `ImportError` at collect | n/a   | No automated test; pytest will fail to collect the whole suite              |
| A new roundtrip case is added without also covering the save/load parity run | Missing coverage         | FR-26 | Code review: the three parametrized functions must share `ROUNDTRIP_CASES`  |
| Internal module imported in `test_roundtrip.py`                              | n/a                      | n/a   | Code review: this file is public-API-only by contract                       |

## Related reading

- [Public Tokenizer API](public-api.md): the five methods the suite
  exercises; the delegation-only contract this suite verifies end-to-end.
- [Encode and Decode](encode-decode.md): the algorithm underneath every
  roundtrip assertion; the per-rank merge and strict-UTF-8 decode paths.
- [Phase 2 Fixtures](../phase-2/fixtures.md): the `tiny.txt` corpus
  consumed by the session-scoped `trained_tokenizer` fixture; byte
  invariants and the whitespace-preservation rule.
- [Phase 2 Persistence](../phase-2/persistence.md): the atomic save and
  strict load that `test_post_load_*` exercises through the public API.
- [`docs/bpetite-prd-v2.md`](../bpetite-prd-v2.md): FR-17, FR-21, FR-22,
  FR-23, FR-25, FR-26.
- [`tests/test_roundtrip.py`](../../tests/test_roundtrip.py): the full
  55-test suite.
- [`tests/conftest.py`](../../tests/conftest.py): the session-scoped
  `trained_tokenizer` fixture and the existing fixture surface it joins.
