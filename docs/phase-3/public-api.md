---
title: Public Tokenizer API
description: The five-method contract, private instance state, and delegation-only implementation of bpetite.Tokenizer.
slug: phase-3-public-api
order: 22
category: Phase 3
published: true
---

# Public Tokenizer API — five-method contract, delegation-only implementation

## TL;DR

- `Tokenizer` is the single public name exported from `bpetite`; the full
  surface is five methods — `train`, `encode`, `decode`, `save`, `load` —
  matching PRD lines 254–269 exactly.
- Instance state is private (`_vocab`, `_merges`, `_special_tokens`); `train`
  and `load` are classmethod factories, and `encode` always reads its `text`
  parameter directly so a tokenizer never holds stored input across calls.
- Every public method delegates to a private module, so the class body
  contains no algorithmic logic and the published contract is stable under
  internal refactors.

## What lives here

| File                          | Purpose                                                                                                                     |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `src/bpetite/_tokenizer.py`   | `Tokenizer` class; constructor stores normalized state, each public method is a one-line wrapper over the internal function |
| `src/bpetite/__init__.py`     | Exports exactly one name — `Tokenizer` — via `__all__ = ["Tokenizer"]`; no convenience re-exports                           |
| `src/bpetite/_trainer.py`     | `train_bpe` and `TrainerResult`; `Tokenizer.train` calls it and normalizes the result into mutable `dict`/`list` state      |
| `src/bpetite/_encoder.py`     | `encode`; `Tokenizer.encode` forwards the method argument `text` directly                                                   |
| `src/bpetite/_decoder.py`     | `decode`; `Tokenizer.decode` forwards the method argument `token_ids` directly                                              |
| `src/bpetite/_persistence.py` | `save` and `load`; `Tokenizer.save` and `Tokenizer.load` are delegation wrappers with identical exception semantics         |

## Key invariants

| Reference                                | Invariant                                                                                                               | Consequence if violated                                                                                                                         |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| PRD §Public API Contract (lines 254–269) | The class exposes exactly five public methods: `train`, `encode`, `decode`, `save`, `load`. No additional public names. | Downstream code (including the Task 4-1 CLI) couples to nonexistent or renamed methods; the shipped API drifts from the PRD.                    |
| Task 3-3 AC2                             | `from bpetite import Tokenizer` resolves, and `Tokenizer` is the only public name on the `bpetite` module.              | `from bpetite import *` leaks internal helpers; the public surface becomes unclear; internal renames break unwitting callers.                   |
| Task 3-3 implementation note             | `Tokenizer.encode` passes its method argument `text` to the encoder; no stored attribute is read.                       | A cached `self._text` would make instances stateful; `tok.encode("a"); tok.encode("b")` would return the first call's IDs for the second.       |
| PRD §Public API Contract                 | `train` and `load` are `@classmethod` factories returning `"Tokenizer"`.                                                | Calling on the class (not an instance) fails, loses type information, or returns the raw internal triple instead of a wrapped `Tokenizer`.      |
| Phase 3 design                           | Every public method delegates to a private module; no algorithmic logic lives in the class body.                        | Internal refactors of `_encoder.py` or `_persistence.py` force `Tokenizer` edits; the class becomes a duplicate implementation surface.         |
| FR-27 / FR-28 (via delegation)           | `save` atomically writes through a same-directory temp file and raises `FileExistsError` when `overwrite=False`.        | A crashed save leaves a partial artifact; a second training run silently overwrites a committed file.                                           |
| FR-29 (via delegation)                   | `load` validates schema version, required keys, shapes, byte ranges, and the special-token invariants before returning. | A corrupt or hand-edited artifact loads without error and produces a broken tokenizer whose encode output no longer matches the training state. |

## Walkthrough

### The exact public surface

```python
>>> import bpetite
>>> sorted(name for name in dir(bpetite) if not name.startswith("_"))
['Tokenizer']
>>> bpetite.__all__
['Tokenizer']
```

Only `Tokenizer` is public. Every other name on the `bpetite` module is an
internal submodule (`_encoder`, `_decoder`, `_tokenizer`, `_persistence`,
`_pretokenizer`, `_trainer`, `_constants`) loaded as a side effect of the
import chain. They are underscore-prefixed and carry no backward-compatibility
guarantee.

### The five-method signature block

```python
>>> import inspect
>>> from bpetite import Tokenizer
>>> for name in ("train", "encode", "decode", "save", "load"):
...     print(f"{name:>7}: {inspect.signature(getattr(Tokenizer, name))}")
  train: (corpus: str, vocab_size: int) -> 'Tokenizer'
 encode: (self, text: str) -> list[int]
 decode: (self, token_ids: collections.abc.Sequence[int]) -> str
   save: (self, path: str, overwrite: bool = False) -> None
   load: (path: str) -> 'Tokenizer'
```

`train` and `load` are classmethods, so their rendered signatures start
directly with the non-`self` arguments — the `cls` parameter is absorbed
by the descriptor.

### End-to-end session

```python
from pathlib import Path
from bpetite import Tokenizer

corpus = "the quick brown fox jumps over the lazy dog\n" * 5
tok = Tokenizer.train(corpus, vocab_size=300)

ids = tok.encode("the quick brown fox")
text = tok.decode(ids)
assert text == "the quick brown fox"

artifact = Path("/tmp/bpetite-demo.json")
artifact.unlink(missing_ok=True)
tok.save(str(artifact))

reloaded = Tokenizer.load(str(artifact))
assert reloaded.encode("the quick brown fox") == ids
assert reloaded.decode(ids) == text
```

Three observable properties fall out of this session:

1. `Tokenizer.train` returns a `Tokenizer` instance even though the underlying
   `train_bpe` function returns a `TrainerResult` dataclass. The classmethod
   normalizes `TrainerResult.vocab` (typed `Mapping[int, bytes]`) into a
   mutable `dict[int, bytes]` and `TrainerResult.merges` (typed
   `tuple[tuple[int, int], ...]`) into a mutable `list[tuple[int, int]]`
   before handing off to `__init__`. The persistence layer accepts the
   normalized shapes directly, so no further conversion is needed at save
   time.
2. `tok.encode("the quick brown fox")` forwards the method argument `text`
   unchanged to `bpetite._encoder.encode`. There is no stored-input cache:
   calling `tok.encode("another string")` immediately afterward sees the new
   input and produces the IDs for `"another string"`, never those of the
   previous call.
3. `reloaded.encode(...)` and `reloaded.decode(...)` return values identical
   to the pre-save tokenizer. The roundtrip invariant (FR-25) holds through
   the save/load boundary; see [Roundtrip Suite](roundtrip-suite.md) for the
   full 55-case proof.

### Delegation, not reimplementation

Every public method is a one-line wrapper over its internal counterpart. For
reference, the encode path (`src/bpetite/_tokenizer.py:78`):

```python
def encode(self, text: str) -> list[int]:
    return _encode(text, self._merges, self._special_tokens)
```

`_encode` is `bpetite._encoder.encode`, imported at module load time with an
underscore-prefixed alias so the class method does not shadow the private
function name inside the module. The same pattern applies to `decode`,
`save`, and `load`. The class body holds no algorithmic logic; if the
encoder's merge-application strategy changes, `Tokenizer.encode` does not
need to change at all.

## Failure modes

| Failure                                                                    | Exception type             | Reference                       | Caught by                                                                                     |
| -------------------------------------------------------------------------- | -------------------------- | ------------------------------- | --------------------------------------------------------------------------------------------- |
| `vocab_size < 256` passed to `Tokenizer.train`                             | `ValueError`               | FR-9 (via `train_bpe`)          | `tests/test_roundtrip.py::test_train_below_base_vocab_raises_value_error[-1\|0\|1\|100\|255]` |
| Unknown token ID passed to `Tokenizer.decode`                              | `KeyError`                 | FR-22 (via `_decoder.decode`)   | `tests/test_roundtrip.py::test_decode_unknown_id_raises_key_error`                            |
| Invalid concatenated UTF-8 bytes in `Tokenizer.decode`                     | `UnicodeDecodeError`       | FR-23 (via `_decoder.decode`)   | `tests/test_roundtrip.py::test_decode_invalid_utf8_raises`                                    |
| `Tokenizer.save` to an existing path without `overwrite=True`              | `FileExistsError`          | FR-27 (via `_persistence.save`) | `tests/test_persistence.py::test_save_refuses_to_overwrite_existing_file_by_default`          |
| `Tokenizer.save` to a path whose parent directory does not exist           | `FileNotFoundError`        | FR-28 (via `_persistence.save`) | `tests/test_persistence.py::test_save_raises_file_not_found_when_parent_directory_missing`    |
| `Tokenizer.load` of a corrupt artifact (missing key, bad shape, bad bytes) | `KeyError` or `ValueError` | FR-29 (via `_persistence.load`) | `tests/test_persistence.py::test_load_rejects_*` (the full rejection suite, 12 cases)         |

### Silent failure specific to `Tokenizer.encode`

One silent failure has no automated test because it is a design-time
invariant enforced by the Task 3-3 implementation note:

> `Tokenizer.encode` must call the encoder with the method argument `text`,
> not any stored text attribute.

An implementation that caches the last encoded text on `self._text` and
reads from it inside `encode` still returns the correct IDs on any single
call — the cache is seeded from the method argument. Two consecutive calls
with different inputs silently return the first call's IDs for the second.
The invariant is enforced by the tight wrapper at
`src/bpetite/_tokenizer.py:78`; any change to that wrapper that references
`self` state for the input text must be rejected on sight during review.

## Related reading

- [Encode and Decode](encode-decode.md) — how `Tokenizer.encode` and
  `Tokenizer.decode` actually produce and consume IDs, with a worked example
  traced end-to-end through special-token extraction, pre-tokenization, and
  per-rank merge application.
- [Roundtrip Suite](roundtrip-suite.md) — the 55-test proof of FR-25 against
  the public API only, including the save/load parity coverage.
- [Phase 2 Persistence](../phase-2/persistence.md) — the `save`/`load`
  contract that `Tokenizer.save` and `Tokenizer.load` delegate to.
- [Phase 2 Core Algorithm](../phase-2/core-algorithm.md) — the `train_bpe`
  contract that `Tokenizer.train` delegates to and normalizes into mutable
  instance state.
- [`docs/bpetite-prd-v2.md`](../bpetite-prd-v2.md) — FR-9, FR-16, FR-17,
  FR-20, FR-21, FR-25 through FR-29; §Public API Contract, lines 254–269.
- [`src/bpetite/_tokenizer.py`](../../src/bpetite/_tokenizer.py) — the full
  `Tokenizer` class; ~130 lines total, no algorithmic logic.
- [`src/bpetite/__init__.py`](../../src/bpetite/__init__.py) — the export
  line that locks the public surface to `Tokenizer` only.
