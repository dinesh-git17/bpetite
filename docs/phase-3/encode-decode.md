---
title: Encode and Decode
description: Special-token extraction, per-rank merge application, and strict UTF-8 reconstruction for the bpetite encoder and decoder.
slug: phase-3-encode-decode
order: 21
category: Phase 3
published: true
---

# Encode and Decode: special-token extraction, per-rank merge passes, strict UTF-8 reconstruction

## TL;DR

- The encoder extracts exact literal occurrences of `<|endoftext|>` first,
  pre-tokenizes each remaining segment into UTF-8 byte chunks, and applies
  the learned merges in rank order with a single non-overlapping
  left-to-right pass per rank.
- The decoder is a single expression: look each token id up in the vocab,
  concatenate the bytes, decode once with UTF-8 strict mode. `KeyError`
  and `UnicodeDecodeError` propagate unchanged.
- The roundtrip invariant `decode(encode(text)) == text` holds by
  construction: the encoder's total byte output for ordinary segments
  equals `text.encode("utf-8")` for that segment, reserved special tokens
  map to vocab entries containing the literal's UTF-8 bytes, and the
  decoder joins and strict-decodes.

## What lives here

| File                           | Purpose                                                                                                                                   |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `src/bpetite/_encoder.py`      | `encode`, `_encode_ordinary`, `_apply_merge`; all merge-application logic for the encode path                                             |
| `src/bpetite/_decoder.py`      | `decode`; one expression, no branching                                                                                                    |
| `src/bpetite/_pretokenizer.py` | `pretokenize`; segments are split into UTF-8 byte chunks via the canonical regex before merge application                                 |
| `src/bpetite/_constants.py`    | `END_OF_TEXT_TOKEN = "<\|endoftext\|>"` and `PRETOKENIZER_PATTERN`; both are imported by the encoder transitively via the pre-tokenizer   |
| `tests/test_roundtrip.py`      | FR-17, FR-21, FR-22, FR-23, FR-25 coverage through the public API: empty-string edges, exception semantics, and the full roundtrip matrix |

## Key invariants

| FR    | Invariant                                                                                                                                                                                                     | Consequence if violated                                                                                                                        |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| FR-16 | The encoder first extracts exact literal occurrences of `<\|endoftext\|>`, then pre-tokenizes non-special segments into chunks, then applies learned merges by merge rank with non-overlapping LTR semantics. | Partial special strings get mis-extracted, or chunk bytes are double-merged, or rank order is violated; deterministic fixtures drift silently. |
| FR-17 | `encode("")` returns `[]`.                                                                                                                                                                                    | Callers must special-case empty input; downstream length assertions break.                                                                     |
| FR-18 | Partial special strings such as `<\|endoftext` and `endoftext\|>` are treated as ordinary text.                                                                                                               | A false match consumes characters belonging to adjacent text; the roundtrip invariant breaks for any input containing a partial literal.       |
| FR-19 | Consecutive special tokens encode as consecutive special-token ids, one per occurrence.                                                                                                                       | Two `<\|endoftext\|>` in a row collapse into one id, or the second occurrence falls through into ordinary-text encoding.                       |
| FR-20 | The decoder maps each token id to its bytes, concatenates, and decodes once with UTF-8 strict mode.                                                                                                           | Multi-byte UTF-8 characters split across token boundaries decode incorrectly, or invalid bytes silently substitute replacement characters.     |
| FR-21 | `decode([])` returns `""`.                                                                                                                                                                                    | Callers must special-case empty id sequences; downstream string assertions break.                                                              |
| FR-22 | Unknown token ids raise `KeyError`.                                                                                                                                                                           | Corrupt or out-of-range ids silently map to empty strings or substitution characters; the decoder hides data loss.                             |
| FR-23 | Invalid concatenated UTF-8 bytes raise `UnicodeDecodeError`.                                                                                                                                                  | Invalid-byte sequences decode to U+FFFD substitutions under `errors="replace"`; the decoder hides corruption.                                  |
| FR-24 | Decoding a reserved special token id returns the literal string `<\|endoftext\|>`.                                                                                                                            | The reserved id decodes to garbled bytes or an empty string; round-trip breaks for any text containing the literal.                            |

## Walkthrough

### The encode pipeline

```
  input text (str)
      |
      v
  split on exact literal <|endoftext|>   <-- exact-literal match only; partial
      |                                       prefixes/suffixes flow through
      v                                       as ordinary text
  [segment][special id][segment][special id]...
      |                    |
      v                    v
  pretokenize()       emit directly
      |                    |
      v                    |
  list[bytes] chunks       |
      |                    |
      v                    |
  for each chunk:          |
      tokens = list(bytes) |  <-- base byte ids 0..255, one per byte
      for rank in 0..K-1:  |
          tokens = apply_merge(tokens, merges[rank], 256 + rank)
              (non-overlapping left-to-right, single full pass per rank)
      |                    |
      v                    v
          emit tokens into the final id sequence
```

Two design choices matter here. First,
special-token extraction happens **before** pre-tokenization, not inside it.
Keeping extraction outside the pre-tokenizer means the canonical GPT-2
regex never sees `<|endoftext|>` at all, so the literal cannot be
accidentally split by the regex's punctuation run or letter-run rules.
Second, merges are applied **rank by rank**, with a full non-overlapping
left-to-right pass at each rank, rather than by searching for the
currently-best pair on every iteration. Both strategies are equivalent for
correctness on the standard byte-level BPE merge list; the per-rank pass
matches the training-time replacement semantics from FR-10 verbatim and is
the style the task schema specifies.

### Worked example

Train a minimal tokenizer on the two-word corpus `"ab ab ab"` at
`vocab_size=258` (256 base bytes + up to 2 merges). This setup is small
enough to trace on paper and runnable as-is against the current repo.

```python
from bpetite import Tokenizer

tok = Tokenizer.train("ab ab ab", vocab_size=258)
```

The trainer pre-tokenizes the corpus into three chunks, counts pairs with
multiplicity, and learns exactly two merges before early-stopping:

- chunks from `pretokenize("ab ab ab")` → `[b"ab", b" ab", b" ab"]`
- rank 0: pair `(97, 98)` (`b"a"` + `b"b"`) → new token id `256` with
  bytes `b"ab"`
- rank 1: pair `(32, 256)` (`b" "` + `b"ab"`) → new token id `257` with
  bytes `b" ab"`
- mergeable vocab size: `258` (`256 + 2`)
- reserved special token: `<|endoftext|>` at id `258`

See [Phase 2 Core Algorithm](../phase-2/core-algorithm.md) for the full
training trace of the same corpus.

Now encode a mixed-special input:

```python
ids = tok.encode("ab<|endoftext|>ab")
assert ids == [256, 258, 256]
```

Trace step by step:

1. **Special-token extraction.** The encoder scans the input text
   left to right. At position 0 it checks `text.startswith("<|endoftext|>", 0)`;
   the input starts with `"ab"`, so no match. It advances to position 2 and
   finds the literal, emits id `258` for it, and records that segment
   `[0:2] = "ab"` came before. It advances past the literal to position 15
   and treats the remainder `"ab"` as the next segment.
2. **Segment pre-tokenization.** For the first segment `"ab"`,
   `pretokenize("ab")` returns `[b"ab"]`, one chunk. Same for the trailing
   `"ab"` segment.
3. **Merge application on the first chunk.** Start from the base-byte
   id list `[97, 98]`. Rank 0 is `(97, 98)` → id `256`; the full pass
   finds one match at position 0, emits id `256`, and advances. The
   resulting token list for this chunk is `[256]`. Rank 1 is
   `(32, 256)` → id `257`; no match (no `32` adjacent to the `256`). The
   chunk is done: contributes `[256]`.
4. **Emit the special id in source order.** `[256]` from the first
   segment, then `258` for the special, then `[256]` from the trailing
   segment.
5. **Final result:** `[256, 258, 256]`.

Decoding back is a single expression:

```python
text = tok.decode(ids)
assert text == "ab<|endoftext|>ab"
```

Step by step:

1. Look each id up in the vocab. `vocab[256] = b"ab"`,
   `vocab[258] = b"<|endoftext|>".encode("utf-8")` (the literal's UTF-8 bytes,
   stored at training time; see FR-24), `vocab[256] = b"ab"`.
2. Concatenate: `b"ab" + b"<|endoftext|>" + b"ab" = b"ab<|endoftext|>ab"`.
3. Decode once with UTF-8 strict mode: `"ab<|endoftext|>ab"`.

The input and the decoded output are byte-identical, and the roundtrip
invariant holds.

### Partial special strings flow through as ordinary text

```python
partial = tok.encode("<|endoftext")
assert tok.decode(partial) == "<|endoftext"
```

At position 0, `"<|endoftext".startswith("<|endoftext|>")` is `False`. The
input is strictly shorter than the literal. Special-token extraction makes
no match at any position in the 11-character input. The whole string flows
into `_encode_ordinary`, which pre-tokenizes it via the canonical regex
into two chunks (`b"<|"` and `b"endoftext"`), converts each chunk to base
byte ids, and applies the two ranked merges. Neither merge matches: the
chunks contain no `(97, 98)` pair and no `(32, 256)` pair. The final
token list is simply the original bytes, and the decoder joins them back
into the original string.

FR-18 is enforced exactly this way for all three partial variants
covered by the roundtrip suite: `<|endoftext`, `endoftext|>`, and `<|endo`.

### The `[a, b, a, b]` invariant

A single merge rank scans the token list once and replaces every
non-overlapping match left to right. Concretely, for token list
`[97, 98, 97, 98]` (bytes for `"abab"`) with merge `(97, 98) → 256`, one
pass emits `[256, 256]`. The cursor advances by two after each match so
overlapping candidates are never revisited. This is the same
non-overlapping LTR rule the trainer uses at merge time (FR-10), which is
why the encoder's output matches what the trainer would have produced on
the same bytes.

For three identical adjacent tokens `[x, x, x]` with merge `(x, x)`, the
result is `[xx, x]`, not `[x, xx]`: the first pair is consumed, the
cursor advances past the consumed pair, and the trailing `x` is emitted
unchanged. See
`tests/test_trainer.py::test_train_non_overlapping_merge_on_triple_emits_merged_then_trailing`
for the training-time pin on the same invariant.

### The decoder in one line

```python
# src/bpetite/_decoder.py
def decode(token_ids: Sequence[int], vocab: dict[int, bytes]) -> str:
    return b"".join(vocab[token_id] for token_id in token_ids).decode(
        "utf-8", errors="strict"
    )
```

No branching, no pre-loops, no special-case for the empty sequence
(`b"".join(iter([]))` is already `b""`, and `b"".decode("utf-8") == ""`).
`KeyError` propagates out of the generator expression when an id is
missing from `vocab`. `UnicodeDecodeError` propagates out of the final
`decode` call when the concatenated bytes are not valid UTF-8. The strict
mode is explicit, not the Python default, because the PRD requires it
and a silent fallback to `errors="replace"` is the most common silent
failure for this kind of code.

## Failure modes

| Failure                                                             | Exception type          | FR    | Caught by                                                                            |
| ------------------------------------------------------------------- | ----------------------- | ----- | ------------------------------------------------------------------------------------ |
| `encode("")` does not return `[]`                                   | `AssertionError` (test) | FR-17 | `tests/test_roundtrip.py::test_encode_empty_returns_empty_list`                      |
| `decode([])` does not return `""`                                   | `AssertionError` (test) | FR-21 | `tests/test_roundtrip.py::test_decode_empty_returns_empty_string`                    |
| Unknown token id in `decode`                                        | `KeyError`              | FR-22 | `tests/test_roundtrip.py::test_decode_unknown_id_raises_key_error`                   |
| Invalid concatenated UTF-8 in `decode`                              | `UnicodeDecodeError`    | FR-23 | `tests/test_roundtrip.py::test_decode_invalid_utf8_raises`                           |
| Partial special string mis-extracted as a special token             | `AssertionError` (test) | FR-18 | `tests/test_roundtrip.py::test_roundtrip[partial special prefix\|suffix\|short-...]` |
| Consecutive specials collapse into a single id                      | `AssertionError` (test) | FR-19 | `tests/test_roundtrip.py::test_roundtrip[consecutive specials-...]`                  |
| Decoding the reserved special id does not produce `<\|endoftext\|>` | `AssertionError` (test) | FR-24 | `tests/test_roundtrip.py::test_roundtrip[single endoftext-...]`                      |

### Silent failure modes called out by name

Three encode/decode bugs are easy to miss: they pass the
obvious tests and surface only against specific constructions. The
roundtrip suite pins each one with a dedicated case.

**Single-match-per-rank encoder bug.** An implementation that scans for the
ranked pair once, applies one replacement, and advances to the next rank
still produces correct output when every pair has at most one match per
chunk. Inputs where the same pair appears multiple times in a single
chunk expose it. Any multi-match roundtrip case catches it in the suite;
the minimal reproducer is a chunk like `[97, 98, 97, 98]` with merge
`(97, 98)`, which must emit `[256, 256]` in a single pass, not `[256, 97, 98]`.

**Partial-special false match.** An implementation that uses `str.find`
or a regex for special extraction without bounding the match to the exact
literal can match `<|endoftext|>` starting inside a partial string like
`"...<|endoftext|>..."` but also silently against a prefix like
`"<|endoftext"`. The three partial-special roundtrip cases, prefix,
suffix, and the shorter `<|endo`, expose this immediately because the
decoded output would drop the mismatched tail or consume too many
characters.

**Decoder `errors="replace"` instead of `errors="strict"`.** Passing
`errors="replace"` to the final `bytes.decode` call silently substitutes
invalid byte sequences with U+FFFD instead of raising
`UnicodeDecodeError`. Every valid input still roundtrips, so this bug
never appears outside the invalid-UTF-8 test. The dedicated case uses
`decode([0x80])`, a lone continuation byte with no preceding start byte,
which is always invalid UTF-8 regardless of what merges were learned.

## Related reading

- [Public Tokenizer API](public-api.md): how `Tokenizer.encode` and
  `Tokenizer.decode` wrap `_encoder.encode` and `_decoder.decode` as
  one-line delegations.
- [Roundtrip Suite](roundtrip-suite.md): the full 55-test proof of
  FR-17 through FR-25 via the public `Tokenizer` API only.
- [Phase 2 Core Algorithm](../phase-2/core-algorithm.md): pair counting,
  tie-breaking, and the training-time merge semantics that the encoder
  mirrors at inference time.
- [Phase 2 Persistence](../phase-2/persistence.md): the vocab and merge
  list shapes the encoder and decoder consume.
- [`docs/bpetite-prd-v2.md`](../bpetite-prd-v2.md): FR-16 through FR-25.
- [`src/bpetite/_encoder.py`](../../src/bpetite/_encoder.py): full
  encoder implementation including `_encode_ordinary` and `_apply_merge`.
- [`src/bpetite/_decoder.py`](../../src/bpetite/_decoder.py): full
  decoder; ~50 lines, one expression.
