---
title: Persistence and Artifact Schema v1
description: Atomic save, deterministic serialization, and full loader validation for the bpetite tokenizer artifact.
slug: phase-2-persistence
order: 12
category: Phase 2
published: true
---

# Persistence and Artifact Schema v1 — atomic write, strict reload, byte-deterministic output

## TL;DR

- `save()` writes a versioned JSON artifact atomically via a same-directory temp file; the same
  in-memory state always produces byte-identical output (`sort_keys=True`, compact separators).
- `load()` walks a 19-step validation checklist before returning — every shape, range, and
  cross-field invariant is enforced; no corrupt artifact reaches the caller silently.
- Two determinism gates in `tests/test_persistence.py` catch the two most dangerous silent
  failures: a missing `sort_keys=True` in the serializer, and upstream trainer nondeterminism.

## What lives here

| File                          | Purpose                                                                                                                                            |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/bpetite/_persistence.py` | `save()` and `load()` implementations; `_build_artifact()` and all private validation helpers                                                      |
| `tests/test_persistence.py`   | Round-trip tests, atomic-save semantics, full loader validation checklist, and the two Phase 2 determinism gates                                   |
| `src/bpetite/_constants.py`   | `SCHEMA_VERSION`, `PRETOKENIZER_PATTERN`, and `END_OF_TEXT_TOKEN` — the three values the artifact pins at write time and re-validates at load time |

## Key invariants

| FR    | Invariant                                                                                                                          | Consequence if violated                                                                                        |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| FR-26 | The artifact is a single versioned JSON file that preserves identical encode/decode behavior across save/load boundaries.          | A loaded tokenizer silently produces different token IDs for the same input.                                   |
| FR-27 | `save()` raises `FileExistsError` when the destination exists and `overwrite=False` (the default).                                 | A second training run silently overwrites a committed artifact.                                                |
| FR-28 | The write goes through a temp file in `dest.parent` and is renamed into place with `Path.replace`.                                 | On a cross-device or network mount the rename is not atomic; a crash mid-write produces a partial artifact.    |
| FR-29 | `load()` validates schema version, required keys, key shapes, merge shapes, token ID uniqueness, and byte ranges before returning. | A corrupt or hand-edited artifact loads without error and produces a broken tokenizer.                         |
| FR-12 | `json.dumps(sort_keys=True, separators=(",", ":"))` makes serialization byte-deterministic.                                        | The same in-memory state produces different file bytes on successive saves, breaking the determinism contract. |

## Walkthrough

### Artifact Schema v1 — field-by-field

The loader rejects artifacts with missing fields and with extra fields — the allowed set is
exactly these six keys (per FR-29). The table documents every field in the wire order produced
by `sort_keys=True` (alphabetical):

| Field                  | JSON type | Rule                                                                                                                                                                                                                                                                                                                                                                    |
| ---------------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mergeable_vocab_size` | integer   | Must equal `len(merges) + 256`. Recomputed from `merges` at write time so the stored value cannot drift from the merge list it describes. Booleans rejected (`True` would otherwise pass `isinstance(..., int)`).                                                                                                                                                       |
| `merges`               | array     | Ordered list of `[left_id, right_id]` 2-element arrays. Array index encodes merge rank: index `0` corresponds to token ID `256`. Each element must be a non-negative integer strictly less than the new token's own ID.                                                                                                                                                 |
| `pretokenizer_pattern` | string    | Must equal `PRETOKENIZER_PATTERN` from `src/bpetite/_constants.py`. Locks the artifact to the pre-tokenizer version used during training; a mismatched pattern means the loader would reconstruct a tokenizer whose encoder and trainer disagree on chunk boundaries.                                                                                                   |
| `schema_version`       | integer   | Must equal `SCHEMA_VERSION` (currently `1`). Booleans rejected.                                                                                                                                                                                                                                                                                                         |
| `special_tokens`       | object    | Exactly one key: `"<\|endoftext\|>"`. Value is the integer ID `mergeable_vocab_size`. The corresponding `vocab` entry must hold the UTF-8 bytes of the literal string (per FR-13, FR-14).                                                                                                                                                                               |
| `vocab`                | object    | Maps decimal-string token IDs to byte-value lists. Keys are canonical decimal strings (no leading zeros, no sign, no surrounding whitespace). Values are lists of integers in `0..255`. Covers IDs `0..mergeable_vocab_size` inclusive — the special-token entry is part of `vocab`. Keys are sorted lexicographically as strings (so `"10"` follows `"1"`, not `"2"`). |

#### Vocab entry invariants

The loader validates three categories of vocab entry in sequence:

1. **Base bytes (IDs 0–255).** `vocab[i]` must equal `bytes([i])` for every `i` in `0..255`
   (per FR-8). A corrupt artifact remapping `vocab[0]` to something other than `b"\x00"` would
   produce a tokenizer that decodes byte `0` as the wrong character.

2. **Merge-derived entries (IDs 256..mergeable_vocab_size−1).** For the merge at rank `r`,
   token ID is `256 + r` and `vocab[256+r]` must equal `vocab[left] + vocab[right]`. Each
   merge element must reference an ID strictly less than `256 + r` — no self-reference, no
   forward reference. Validation runs in rank order, so every referenced ID is already
   validated when checked.

3. **Reserved special token (ID `mergeable_vocab_size`).** `vocab[mergeable_vocab_size]` must
   equal `"<|endoftext|>".encode("utf-8")` — the 13-byte sequence
   `[60, 124, 101, 110, 100, 111, 102, 116, 101, 120, 116, 124, 62]`.

#### Set-equality enforcement

The loader enforces set equality — not subset-plus-presence — at three levels:

1. **Top-level keys.** `data.keys() == _REQUIRED_KEYS`. Extra keys raise `ValueError`;
   missing keys raise `KeyError`.
2. **Vocab ID range.** `vocab.keys() == set(range(mergeable_vocab_size + 1))`. A vocab
   missing an ID or containing an ID outside that range is rejected.
3. **Special-token map.** `special_tokens.keys() == {"<|endoftext|>"}`. Exactly one key;
   any other key or additional key raises `ValueError`.

Subset-plus-presence is weaker than set equality: a check like
`"<|endoftext|>" in special_tokens` passes silently if the artifact also contains
`"<|injected|>"`. All three levels use set equality to close that gap.

### Atomic save

```
  in-memory state
  (vocab, merges,
   special_tokens)
        |
        v
  _build_artifact()
        |
        v
  json.dumps(sort_keys=True,
             separators=(",", ":"))
        |
        v
  mkstemp(dir=dest.parent)  <-- must be same filesystem as dest
        |
        v
  write JSON to temp file
        |
        v
  Path.replace(dest)        <-- atomic rename on POSIX
```

The temp file must live in `dest.parent` (see `src/bpetite/_persistence.py:107`). If the
temp file were in `/tmp` and the destination were on a mounted network share, `os.rename`
would cross a device boundary; POSIX then falls back to a non-atomic copy-then-delete. A
crash between the copy and the delete leaves the destination in a partial state. Pinning
`dir=dest.parent` ensures both paths share the same filesystem so the rename is a single
metadata operation.

This failure mode has no automated test — it only surfaces at runtime on specific mount
configurations. The constraint is enforced by code structure, not by CI.

### Duplicate-key and non-standard constant rejection

Python's `json.loads` silently keeps the last value for duplicate object keys. A crafted
artifact could use that to smuggle a second `schema_version` past validation or to override
a vocab entry after it passes the byte-range check. The loader rejects duplicates at parse
time via `object_pairs_hook=_reject_duplicate_keys` (see `src/bpetite/_persistence.py:154`).

`parse_constant=_reject_nonstandard_constants` rejects `NaN`, `Infinity`, and `-Infinity`
at parse time (see `src/bpetite/_persistence.py:155`). Python's `json` module accepts these
by default despite RFC 8259 prohibiting them. A crafted artifact could plant them inside an
unrecognized key to stay silent through the required-key check and carry a non-finite value
into the in-memory state.

### Loader validation checklist

The loader walks these steps in order. An artifact that fails step `n` never reaches step
`n+1`. Steps correspond to code in `src/bpetite/_persistence.py:145–232`.

| Step | Check                                                                                                                                                                          | Exception    | FR           |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------ | ------------ |
| 1    | File is valid UTF-8 (`UnicodeDecodeError` is wrapped and re-raised as `ValueError` to match the documented contract)                                                           | `ValueError` | FR-29        |
| 2    | File is valid JSON; no duplicate object keys; no `NaN`/`Infinity` constants                                                                                                    | `ValueError` | FR-29        |
| 3    | Top-level value is a JSON object                                                                                                                                               | `ValueError` | FR-29        |
| 4    | `schema_version` key is present                                                                                                                                                | `KeyError`   | FR-29        |
| 5    | `schema_version` is an integer, not a boolean                                                                                                                                  | `ValueError` | FR-29        |
| 6    | `schema_version == 1`                                                                                                                                                          | `ValueError` | FR-29        |
| 7    | All six required top-level keys are present                                                                                                                                    | `KeyError`   | FR-29        |
| 8    | No extra top-level keys                                                                                                                                                        | `ValueError` | FR-29        |
| 9    | `pretokenizer_pattern` is a string                                                                                                                                             | `ValueError` | FR-29        |
| 10   | `pretokenizer_pattern` matches the canonical pattern                                                                                                                           | `ValueError` | FR-29        |
| 11   | `merges` is a list of `[int, int]` pairs; each element is a non-negative integer                                                                                               | `ValueError` | FR-29        |
| 12   | `mergeable_vocab_size` is an integer, not a boolean                                                                                                                            | `ValueError` | FR-29        |
| 13   | `mergeable_vocab_size == len(merges) + 256`                                                                                                                                    | `ValueError` | FR-29        |
| 14   | `vocab` is a dict; keys are canonical decimal strings; values are lists of integers in `0..255`                                                                                | `ValueError` | FR-29        |
| 15   | `vocab` covers every ID in `0..mergeable_vocab_size−1` with no gaps                                                                                                            | `ValueError` | FR-29        |
| 16   | `vocab[i] == bytes([i])` for all base-byte IDs `0..255`                                                                                                                        | `ValueError` | FR-8, FR-29  |
| 17   | `vocab[256+r] == vocab[left] + vocab[right]` for every merge rank `r`; each element references an ID strictly less than `256+r`                                                | `ValueError` | FR-29        |
| 18   | `special_tokens` has exactly the key `"<\|endoftext\|>"`; its ID equals `mergeable_vocab_size`; the corresponding `vocab` bytes equal the UTF-8 encoding of the literal string | `ValueError` | FR-13, FR-29 |
| 19   | `vocab` contains no IDs outside `0..mergeable_vocab_size`                                                                                                                      | `ValueError` | FR-29        |

### Determinism gates

Two tests in `tests/test_persistence.py` enforce the byte-determinism requirement from FR-12.

**Gate 1 — `test_same_state_saved_twice_produces_identical_bytes`**

Saves the same trained state to two different paths and asserts
`first.read_bytes() == second.read_bytes()`. This test catches a missing `sort_keys=True` in
`json.dumps`. Without `sort_keys`, Python dict iteration order is insertion-order-stable in
CPython 3.7+ but is not guaranteed identical across restarts, interpreter versions, or
platforms. The `separators` argument eliminates whitespace variation. Both are load-bearing
for the determinism contract.

**Gate 2 — `test_repeated_training_then_saving_produces_identical_artifacts`**

Trains the same corpus twice with the same `vocab_size`, saves both results, and asserts
byte-identity. This test proves the full pipeline — pre-tokenizer, trainer, and persistence —
is deterministic end-to-end (FR-12). A Gate 1 failure implicates the serializer. A Gate 2
failure with Gate 1 passing implicates the trainer or pre-tokenizer.

### Worked example

The snippet below traces a complete save/load cycle for a two-merge state.

```python
from bpetite._trainer import train_bpe
from bpetite._persistence import save, load
import pathlib, tempfile

# Two merges, one reserved special token.
result = train_bpe("ab ab ab", vocab_size=258)
# result.merges         == ((97, 98), (32, 256))
# result.special_tokens == {"<|endoftext|>": 258}

with tempfile.TemporaryDirectory() as tmp:
    path = str(pathlib.Path(tmp) / "tok.json")
    save(path, dict(result.vocab), list(result.merges), dict(result.special_tokens))
    vocab, merges, special_tokens = load(path)

assert merges == list(result.merges)
assert special_tokens == dict(result.special_tokens)
```

The artifact written by the `save()` call above, annotated field by field. The actual file
uses compact separators and no whitespace; the pretty-printed layout and `//` comments below
are for readability only.

```
{
  "mergeable_vocab_size": 258,         // 256 base bytes + 2 merges
  "merges": [
    [97, 98],                          // rank 0: 'a'(97)+'b'(98) -> token 256
    [32, 256]                          // rank 1: ' '(32)+256 -> token 257
  ],
  "pretokenizer_pattern": "...",       // canonical GPT-2-style regex from _constants.py
  "schema_version": 1,
  "special_tokens": {
    "<|endoftext|>": 258               // first ID at or past mergeable range
  },
  "vocab": {
    "0":   [0],                        // base byte 0x00
    ...
    "97":  [97],                       // base byte 'a'
    "98":  [98],                       // base byte 'b'
    ...
    "255": [255],                      // base byte 0xFF
    "256": [97, 98],                   // merge rank 0: "ab"
    "257": [32, 97, 98],               // merge rank 1: " ab"
    "258": [60,124,101,110,100,111,    // "<|endoftext|>" in UTF-8 (13 bytes)
            102,116,101,120,116,124,62]
  }
}
```

Top-level keys appear in alphabetical order (`sort_keys=True`): `mergeable_vocab_size` sorts
before `merges` because `"a" < "s"`. Vocab keys are also sorted alphabetically as strings:
`"10"` follows `"1"`, not `"2"`.

## Failure modes

| Failure                                | Exception                                 | FR    | Test                                                              |
| -------------------------------------- | ----------------------------------------- | ----- | ----------------------------------------------------------------- |
| File not valid UTF-8                   | `ValueError` (wraps `UnicodeDecodeError`) | FR-29 | _(step 1)_                                                        |
| Malformed JSON                         | `ValueError`                              | FR-29 | `test_load_rejects_malformed_json`                                |
| Duplicate JSON object keys             | `ValueError`                              | FR-29 | `test_load_rejects_duplicate_json_object_keys`                    |
| Missing required top-level key         | `KeyError`                                | FR-29 | `test_load_rejects_missing_required_key`                          |
| Extra top-level keys                   | `ValueError`                              | FR-29 | _(step 8)_                                                        |
| Wrong `schema_version`                 | `ValueError`                              | FR-29 | `test_load_rejects_wrong_schema_version`                          |
| Wrong `pretokenizer_pattern`           | `ValueError`                              | FR-29 | `test_load_rejects_pretokenizer_pattern_mismatch`                 |
| `mergeable_vocab_size` mismatch        | `ValueError`                              | FR-29 | `test_load_rejects_mergeable_vocab_size_mismatch`                 |
| Byte value outside `0..255` in vocab   | `ValueError`                              | FR-29 | `test_load_rejects_invalid_byte_values_in_vocab`                  |
| Malformed merge entry                  | `ValueError`                              | FR-29 | `test_load_rejects_malformed_merges`                              |
| Wrong special-token key                | `ValueError`                              | FR-29 | `test_load_rejects_special_token_with_wrong_key`                  |
| Wrong special-token ID                 | `ValueError`                              | FR-29 | `test_load_rejects_special_token_with_wrong_id`                   |
| Wrong special-token bytes in `vocab`   | `ValueError`                              | FR-29 | `test_load_rejects_special_token_with_wrong_bytes`                |
| Missing `sort_keys=True` in serializer | non-deterministic bytes                   | FR-12 | `test_same_state_saved_twice_produces_identical_bytes`            |
| Trainer nondeterminism                 | non-deterministic bytes                   | FR-12 | `test_repeated_training_then_saving_produces_identical_artifacts` |
| Parent directory missing               | `FileNotFoundError`                       | FR-28 | `test_save_raises_file_not_found_when_parent_directory_missing`   |
| Destination exists, `overwrite=False`  | `FileExistsError`                         | FR-27 | `test_save_refuses_to_overwrite_existing_file_by_default`         |
| Cross-device temp file                 | non-atomic write (runtime only)           | FR-28 | _(no automated test — code-level constraint)_                     |

## Related reading

- [`docs/phase-2/index.md`](index.md) — Phase 2 scope and reading order
- [`docs/phase-2/core-algorithm.md`](core-algorithm.md) — trainer and pre-tokenizer that produce
  the state `save()` consumes
- [`docs/bpetite-prd-v2.md`](../bpetite-prd-v2.md) — FR-12, FR-26 through FR-29
- [`src/bpetite/_persistence.py`](../../src/bpetite/_persistence.py) — implementation
- [`tests/test_persistence.py`](../../tests/test_persistence.py) — full test suite
