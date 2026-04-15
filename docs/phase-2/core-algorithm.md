---
title: Core Algorithm
description: Pre-tokenizer, trainer, tie-breaking, merge application, early stop, and special-token reservation for bpetite.
slug: phase-2-core-algorithm
order: 11
category: Phase 2
published: true
---

# Core Algorithm — pre-tokenize, count, merge, reserve

## TL;DR

- The pre-tokenizer splits text into chunks using a single centralized regex; no pair ever
  bridges a chunk boundary during training or encoding.
- At each merge step the highest-frequency adjacent pair wins; ties break on lexicographic
  tuple ordering — `min(..., key=lambda item: (-count, pair))` — making training fully
  deterministic without a custom comparator.
- Special-token reservation (`<|endoftext|>` at ID `mergeable_vocab_size`) happens after
  merge training completes; the literal is never pre-extracted from the training corpus.

## What lives here

| File                           | Purpose                                                                                                                                                                                                          |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/bpetite/_constants.py`    | Single source of truth for `PRETOKENIZER_PATTERN`, `SCHEMA_VERSION`, and `END_OF_TEXT_TOKEN`; centralizing these prevents the pre-tokenizer, trainer, encoder, and persistence layer from drifting independently |
| `src/bpetite/_pretokenizer.py` | `pretokenize()` — compiles the canonical pattern once at import time and returns UTF-8 byte chunks in source order                                                                                               |
| `src/bpetite/_trainer.py`      | `train_bpe()`, `TrainerResult`, `ProgressEvent`, and the four private helpers: `_count_pairs`, `_select_best_pair`, `_apply_merge_to_words`, `_apply_merge_to_word`                                              |
| `tests/test_trainer.py`        | FR-7 through FR-15 coverage: chunk boundary enforcement, base vocab, vocab size validation, tie-breaking, non-overlapping merges, early stop, determinism, and special-token reservation                         |

## Key invariants

| FR    | Invariant                                                                                                                                         | Consequence if violated                                                                                                               |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| FR-4  | The pre-tokenizer uses the exact pattern in `_constants.py`, compiled with the `regex` package.                                                   | A different pattern produces different chunk boundaries, changing all downstream merge decisions and breaking artifact compatibility. |
| FR-5  | The pre-tokenizer returns chunks in source order and preserves all characters.                                                                    | Encoding and decoding produce mismatched byte streams; the round-trip guarantee breaks.                                               |
| FR-6  | No normalization, case folding, or whitespace trimming is applied at any stage.                                                                   | Different inputs hash to the same token sequence; the tokenizer is no longer injective.                                               |
| FR-7  | Pair counting and merge application are bounded by chunk boundaries.                                                                              | Cross-boundary pairs are counted; the tokenizer merges sequences that span distinct linguistic units.                                 |
| FR-8  | Training starts from 256 base tokens, one per byte value `0..255`; merge IDs are assigned sequentially from 256.                                  | Token IDs conflict or the vocab is incomplete; decoding fails for some byte values.                                                   |
| FR-9  | `vocab_size < 256` raises `ValueError`; `vocab_size == 256` returns the base vocab with zero merges.                                              | Callers receive an unusable tokenizer or no error signal for an invalid request.                                                      |
| FR-10 | The highest-frequency pair is selected each step; ties break by lexicographic tuple ordering; merge application is non-overlapping left-to-right. | Nondeterministic output; two training runs on the same corpus diverge.                                                                |
| FR-11 | Training stops early when no mergeable pairs remain and returns the actual learned `mergeable_vocab_size` without error.                          | Training raises or pads the merge list with invalid entries.                                                                          |
| FR-12 | The same `(corpus, vocab_size)` always produces the same merges and artifact bytes.                                                               | Reproducible experiments become impossible; the CI determinism gates fail.                                                            |
| FR-13 | `<\|endoftext\|>` is reserved at the first ID >= `mergeable_vocab_size` after training completes.                                                 | The special-token ID conflicts with a merge-derived token or is undefined.                                                            |
| FR-14 | `<\|endoftext\|>` is the only reserved special token in v1.                                                                                       | Multiple special tokens introduce ID-assignment complexity not covered by the Artifact Schema v1.                                     |
| FR-15 | Special-token reservation occurs after merge training. During training, `<\|endoftext\|>` in the corpus is treated as ordinary text.              | Pre-extracting the literal distorts pair counts and produces different merges on corpus containing the literal.                       |

## Walkthrough

### The canonical pre-tokenizer pattern

The pattern is defined once in `src/bpetite/_constants.py` and imported by every module that
needs it:

```python
PRETOKENIZER_PATTERN: str = (
    r"""'(?:[sdmt]|ll|ve|re)| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+"""
)
```

This is the GPT-2 pre-tokenizer regex, compiled with the `regex` package rather than stdlib
`re`. The `regex` package is required because `\p{L}` and `\p{N}` are Unicode property
escapes that `re` does not support.

Centralizing the pattern in `_constants.py` prevents drift: if the encoder were to import its
own copy and a character class were edited in one place but not the other, the encoder and
trainer would disagree on chunk boundaries — silently, with no import-time error.

The pattern is compiled exactly once at `_pretokenizer.py` module import time
(`src/bpetite/_pretokenizer.py:14`). Recompiling on every `pretokenize()` call would be
correct but wasteful for large corpora.

### Two-phase training model

```
  corpus (str)
      |
      v
  pretokenize()          <-- chunk boundaries established here; never revisited
      |
      v
  count unique chunks    <-- (pre_token_bytes, corpus_multiplicity) pairs
      |
      v
  merge loop:
    count pairs          <-- within each unique chunk, weighted by multiplicity
    select best pair     <-- highest count; tie-break by lex-min tuple
    apply merge          <-- non-overlapping LTR across all chunks
    repeat until quota or no pairs remain
      |
      v
  reserve special token  <-- after merge loop exits
      |
      v
  TrainerResult
```

The corpus is pre-tokenized once. Every subsequent operation — pair counting, merge
application — works on the chunk representation. Pairs never cross chunk boundaries (FR-7)
because `_count_pairs` iterates `pairwise(word)` independently for each chunk, and
`_apply_merge_to_word` processes each chunk in isolation.

### Pair counting with corpus multiplicity

The trainer does not iterate every position in the corpus. It converts the pre-token list
into a `{unique_chunk: count}` map, then counts pairs per unique chunk and multiplies by
that chunk's corpus frequency:

```python
from collections import Counter
from itertools import pairwise

def _count_pairs(words):
    counts = Counter()
    for word, weight in words.items():   # word is a tuple of int token IDs
        for pair in pairwise(word):
            counts[pair] += weight       # weight is corpus frequency of this chunk
    return counts
```

A chunk that appears 1000 times in the corpus contributes its pairs 1000 times to the count,
without iterating 1000 separate positions. This is equivalent to full corpus iteration but
operates on the unique-chunk set.

### Tie-breaking and determinism

When two or more pairs share the highest frequency, `_select_best_pair` picks the
lexicographically smallest pair:

```python
def _select_best_pair(pair_counts):
    return min(
        pair_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )[0]
```

The key `(-count, pair)` sorts by descending count first, then by ascending tuple value.
Standard Python tuple comparison is element-wise: `(97, 98) < (99, 97)` because `97 < 99`
on the first element. No custom comparator is needed.

The alternative wrong patterns — `max(..., key=count)` with no tie-break, or
`Counter.most_common(1)` which returns first-seen under ties — both produce nondeterministic
output across Python versions and platforms.

The test that distinguishes correct tie-breaking from these wrong patterns is
`tests/test_trainer.py::test_train_tie_breaking_picks_lexicographically_smallest_pair`. The
corpus `"cab"` produces pairs `(99, 97)` and `(97, 98)` each at frequency 1. A first-seen
or max-by-count tie-breaker encounters `(99, 97)` first and returns it; lexicographic
ordering picks `(97, 98)` because `97 < 99`.

A corpus like `"abcd"` where the seen-order matches the lex order cannot distinguish these
rules and is insufficient for this test.

### Non-overlapping left-to-right merge application

`_apply_merge_to_word` scans a single chunk left-to-right. When it finds the target pair at
positions `i` and `i+1`, it emits the new token ID and advances the index by 2, skipping
the overlap:

```python
def _apply_merge_to_word(word, pair, new_id):
    result = []
    i = 0
    while i < len(word):
        if i + 1 < len(word) and word[i] == pair[0] and word[i + 1] == pair[1]:
            result.append(new_id)
            i += 2            # skip the consumed pair; i+1 is not re-examined
        else:
            result.append(word[i])
            i += 1
    return tuple(result)
```

The non-overlapping rule matters for repeated identical tokens. Given chunk `(x, x, x)` and
merge `(x, x)`:

- The left pair at positions 0–1 is consumed; `i` advances to 2.
- Position 2 holds a single `x` with no right neighbor; it is emitted as-is.
- Result: `(xx, x)` — the leading pair merges, the trailing `x` is untouched.
- The alternative `(x, xx)` is never produced because index 1 is never re-examined.

This is verified by
`tests/test_trainer.py::test_train_non_overlapping_merge_on_triple_emits_merged_then_trailing`.

After applying the merge across all chunks, `_apply_merge_to_words` accumulates the results
into a new `{merged_chunk: count}` dict. Two distinct pre-tokens that become identical after
a merge are combined — their counts add. This is the only place corpus multiplicity can
change between steps.

### Early stop

The merge loop runs for at most `vocab_size - 256` iterations. At the start of each
iteration, `_count_pairs` re-counts the current chunk state. If the returned counter is
empty — meaning every chunk in the corpus has collapsed to a single token and no within-chunk
pairs remain — the loop breaks immediately (FR-11).

Early stop is not an error. `TrainerResult.mergeable_vocab_size` reports the actual count
`256 + len(merges)`, which may be smaller than the requested `vocab_size`. The special token
is still reserved at this smaller ID.

The canonical early-stop trigger is a corpus whose chunks all reduce to single tokens before
the quota is filled. The test
`tests/test_trainer.py::test_train_early_stops_instead_of_merging_across_chunk_boundaries`
demonstrates a subtler case: corpus `"ab\nab\nab\nab\nab"` pre-tokenizes into alternating
`b"ab"` and `b"\n"` chunks. After one merge `(97, 98) -> 256`, every `b"ab"` chunk becomes
`(256,)` — a single token. The `b"\n"` chunks were always single tokens. No within-chunk
pairs remain, so training stops at exactly one merge even though `vocab_size=300` was
requested. A flatten-then-count implementation would see the cross-boundary pair `(10, 256)`
four times after the first merge and keep going, producing the wrong merge list.

### Special-token reservation

After the merge loop exits, `train_bpe` assigns `<|endoftext|>` the ID
`mergeable_vocab_size` — the first integer at or past the learned mergeable range — and
populates `vocab[mergeable_vocab_size]` with the UTF-8 bytes of the literal string (per
FR-13, FR-15):

```python
special_token_id = mergeable_vocab_size
vocab[special_token_id] = END_OF_TEXT_TOKEN.encode("utf-8")
special_tokens = {END_OF_TEXT_TOKEN: special_token_id}
```

Reservation happens after training, not before. If `<|endoftext|>` appears in the training
corpus, its bytes flow through pre-tokenization and pair counting like any other text. The
test `test_train_treats_endoftext_literal_in_corpus_as_ordinary_text` confirms this: a
corpus with the literal produces different merges than the same corpus without it. A trainer
that pre-extracted and dropped the literal would produce identical merges, which the test
catches.

The `vocab` entry at the special-token ID is load-bearing for decoding: the decoder resolves
every token ID through a single `vocab` lookup, so the special-token bytes must be present
there — not in a parallel dict.

### Worked example

The snippet below traces `train_bpe("ab ab ab", vocab_size=258)` end-to-end and is
copy-pasteable against the current repo state:

```python
from bpetite._pretokenizer import pretokenize
from bpetite._trainer import train_bpe, _count_pairs, _select_best_pair

corpus = "ab ab ab"

# Step 1: pre-tokenize
chunks = pretokenize(corpus)
# [b"ab", b" ab", b" ab"]

# Step 2: unique chunks with corpus multiplicity
#   b"ab"  -> (97, 98)      x 1
#   b" ab" -> (32, 97, 98)  x 2

words = {(97, 98): 1, (32, 97, 98): 2}

# Step 3: pair counts for merge iteration 1
pair_counts = _count_pairs(words)
# {(97, 98): 3, (32, 97): 2}
#   (97,98) scores 1*1 + 1*2 = 3  [from b"ab" weight 1, and b" ab" weight 2]
#   (32,97) scores 1*2 = 2         [from b" ab" weight 2 only]

best = _select_best_pair(pair_counts)
# (97, 98)  -- count 3, no tie; new token 256 = b"ab"

# After merge 1:
#   (256,)     x 1   [b"ab"  collapsed]
#   (32, 256)  x 2   [b" ab" partially merged]

# Step 4: pair counts for merge iteration 2
# {(32, 256): 2}
# Best: (32, 256) -- count 2, no tie; new token 257 = b" ab"

# After merge 2: (256,) x 1, (257,) x 2 -- no adjacent pairs remain.

result = train_bpe(corpus, 258)
assert result.merges == ((97, 98), (32, 256))
assert result.vocab[256] == b"ab"
assert result.vocab[257] == b" ab"
assert result.mergeable_vocab_size == 258

# Step 5: special-token reservation
# mergeable_vocab_size = 256 + 2 = 258
# <|endoftext|> reserved at ID 258
assert result.vocab[258] == b"<|endoftext|>"
assert dict(result.special_tokens) == {"<|endoftext|>": 258}
```

Note that the chunk `b"ab"` and the two `b" ab"` chunks are processed as three separate
pre-tokens. The pair `(97, 98)` scores 3 because it appears once in the weight-1 chunk and
once in each of the two weight-2 chunks (contributing 2). The pair `(32, 97)` scores only 2
because it appears only in `b" ab"` chunks.

## Failure modes

| Failure                                              | Exception                                  | FR           | Test                                                                    |
| ---------------------------------------------------- | ------------------------------------------ | ------------ | ----------------------------------------------------------------------- |
| `vocab_size < 256`                                   | `ValueError`                               | FR-9         | `test_train_raises_value_error_for_vocab_size_below_256`                |
| Wrong tie-break ordering (non-lexicographic)         | nondeterministic merges                    | FR-10, FR-12 | `test_train_tie_breaking_picks_lexicographically_smallest_pair`         |
| Cross-chunk pair counting                            | wrong merge list; fails early-stop test    | FR-7         | `test_train_early_stops_instead_of_merging_across_chunk_boundaries`     |
| Overlapping merge application                        | wrong vocab entries for repeated tokens    | FR-10        | `test_train_non_overlapping_merge_on_triple_emits_merged_then_trailing` |
| `<\|endoftext\|>` pre-extracted from training corpus | merge list diverges from expected          | FR-15        | `test_train_treats_endoftext_literal_in_corpus_as_ordinary_text`        |
| Early stop treated as error                          | `ValueError` raised on valid sparse corpus | FR-11        | `test_train_early_stops_when_no_mergeable_pairs_remain`                 |

## Related reading

- [`docs/phase-2/index.md`](index.md) — Phase 2 scope and reading order
- [`docs/phase-2/persistence.md`](persistence.md) — how the trained state is serialized and
  reloaded; determinism gate 2 closes the loop on FR-12
- [`docs/bpetite-prd-v2.md`](../bpetite-prd-v2.md) — FR-4 through FR-15
- [`src/bpetite/_trainer.py`](../../src/bpetite/_trainer.py) — implementation
- [`src/bpetite/_pretokenizer.py`](../../src/bpetite/_pretokenizer.py) — pre-tokenizer
- [`src/bpetite/_constants.py`](../../src/bpetite/_constants.py) — canonical pattern and constants
- [`tests/test_trainer.py`](../../tests/test_trainer.py) — full test suite
