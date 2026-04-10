---
name: bpe-algorithm
description: "Provides the exact behavioral contract for the byte-level BPE algorithm in bpetite. Use this skill immediately whenever working on _trainer.py, _encoder.py, or any test file that imports from either — including when implementing pair counting, tie-breaking, merge application, the greedy encoder loop, chunk boundary enforcement, or early stop semantics. Also invoke when the words BPE, merge, tokenizer, train, encode, pair counting, tie-breaking, or merge rank appear in the task. Do not proceed with trainer or encoder implementation without consulting this skill — subtle errors in tie-breaking and the encoder loop are the most common failure mode and will produce wrong merge orders that only surface against deterministic fixtures."
---

# BPE Algorithm Behavioral Contract

This skill encodes the exact algorithmic rules for the `bpetite` byte-level
BPE tokenizer. Every rule here is a correctness requirement, not a style
preference. Violating any one of them produces wrong output that may not
surface until you run deterministic fixture tests.

Read all six sections before writing or modifying any trainer or encoder code.

---

## 1. Base Vocabulary Initialization

The vocabulary starts with exactly **256 entries** corresponding to byte
values 0 through 255, inclusive. Each entry maps a token ID to a single byte:

```python
vocab: dict[int, bytes] = {i: bytes([i]) for i in range(256)}
```

- Token IDs 0–255 are permanently reserved for base byte tokens.
- Merge-derived token IDs are assigned **sequentially starting at 256**.
- The first merge produces token ID 256, the second produces 257, and so on.
- The reserved special token `<|endoftext|>` is appended **after** merge
  training completes and receives the first ID ≥ the final mergeable vocab
  size.
- `vocab_size` always refers to the **mergeable** vocabulary size (base +
  merges). It never includes the reserved special token in its count.

**Watch out for:** any code that initializes fewer than 256 base tokens, or
assigns merge IDs starting at any value other than 256.

---

## 2. Chunk Boundary Enforcement

The pre-tokenizer splits input text into non-overlapping chunks using the
canonical `regex` pattern. Pair counting and merge application operate
**independently per chunk**. A pair can never bridge the last token of one
chunk and the first token of the next.

This means:

- Pair frequency counting sums across all chunks but **never counts a pair
  that straddles a chunk boundary**.
- When applying a merge, only tokens within the same chunk are candidates.
- Two adjacent tokens `t[-1]` (last of chunk N) and `t[0]` (first of chunk
  N+1) are never a candidate pair, regardless of their values.

**Implementation pattern:** maintain the corpus as a list of lists (each
inner list is one chunk's token sequence). Iterate over the outer list when
counting and applying merges. Never flatten to a single sequence.

```python
# Correct: corpus is list[list[int]]
chunks: list[list[int]] = [
    list(chunk_bytes) for chunk_bytes in pretokenize(corpus)
]

# Wrong: do not flatten
flat = [tok for chunk in chunks for tok in chunk]  # NO
```

**Test for this with a crafted corpus:** choose a corpus where the only
occurrence of a candidate pair (a, b) is the last token of one chunk and
the first token of the next. That pair must never appear in the merge list.

---

## 3. Pair Counting and Tie-Breaking

At each training step:

1. Count the frequency of every adjacent pair across all chunks (respecting
   boundaries as above).
2. Select the **most frequent pair**.
3. When multiple pairs share the highest frequency, break the tie by selecting
   the **lexicographically smallest pair** using standard Python tuple
   comparison.

**The tie-breaking rule is `min(candidates)`, not `max()`, not dict insertion
order, not any other heuristic.**

```python
# Correct tie-breaking
best_pair = min(candidates_with_max_freq)  # min() on a set/list of tuples

# Wrong
best_pair = max(candidates_with_max_freq)           # NO
best_pair = next(iter(candidates_with_max_freq))    # NO (dict order)
```

Python tuple comparison is lexicographic: `(97, 98) < (97, 99)` because the
first elements are equal and `98 < 99`. So among `{(97, 99), (97, 98)}` both
at frequency 5, `min()` selects `(97, 98)`.

**Why this matters:** a wrong tie-breaking rule produces a different merge
order. The merge order determines every token ID above 255. A downstream test
that compares the saved artifact byte-for-byte will fail — but the failure
message will look like a general mismatch, not an obvious tie-breaking error.
The only way to catch this reliably is a crafted corpus that forces a tie.

---

## 4. Non-Overlapping Left-to-Right Merge Application

When applying the selected merge pair `(a, b)` to a token sequence, scan
left to right and replace the **first occurrence** of adjacent `a, b` with
the new merged token `ab`, then continue scanning from **immediately after
the merged token**. Do not revisit tokens before the merge point.

This produces **non-overlapping** replacements:

```
Input:  [a, b, a, b]  applying merge (a, b) → ab
Step 1: pos 0: found (a, b) → emit ab, advance to pos 2
Step 2: pos 2: found (a, b) → emit ab, advance to pos 4
Result: [ab, ab]  ✓

Input:  [a, a, a]  applying merge (a, a) → aa
Step 1: pos 0: found (a, a) → emit aa, advance to pos 2
Step 2: pos 2: only one token left, no pair → emit a
Result: [aa, a]  ✓  (NOT [a, aa])
```

The **`[1,1,1] → [new,1]` invariant**: given three identical adjacent tokens
`[x, x, x]` and a merge `(x, x)`, the result is `[xx, x]`. The first pair
is merged; the second pair (now involving the already-consumed right token) is
skipped. This is the direct consequence of advancing past the consumed pair.

**Implementation sketch:**

```python
def apply_merge(
    tokens: list[int],
    pair: tuple[int, int],
    new_id: int,
) -> list[int]:
    result: list[int] = []
    i = 0
    while i < len(tokens):
        if i < len(tokens) - 1 and (tokens[i], tokens[i + 1]) == pair:
            result.append(new_id)
            i += 2          # skip both tokens of the consumed pair
        else:
            result.append(tokens[i])
            i += 1
    return result
```

Apply this function to every chunk independently on each merge step.

---

## 5. Early Stop Semantics

If at any training iteration no pairs exist across any chunk, training stops
immediately — even if the requested `vocab_size` has not been reached.

- The function returns the **actual learned mergeable vocabulary size**
  (256 + number of merges performed), not the requested size.
- No error is raised. Early stop is a valid outcome, not a failure condition.
- If `vocab_size < 256`, raise `ValueError` before training begins.
- If `vocab_size == 256`, skip the merge loop entirely and return the base
  vocabulary plus the reserved special token.

```python
if vocab_size < 256:
    raise ValueError(f"vocab_size must be >= 256, got {vocab_size}")

merges: list[tuple[int, int]] = []
next_id = 256

while next_id < vocab_size:
    pair_counts = count_pairs(chunks)  # empty dict if no pairs exist
    if not pair_counts:
        break                          # early stop — not an error
    best = min(
        (p for p, c in pair_counts.items() if c == max(pair_counts.values())),
    )
    merges.append(best)
    chunks = [apply_merge(chunk, best, next_id) for chunk in chunks]
    next_id += 1

# actual_mergeable_vocab_size == next_id (which may be < vocab_size)
```

---

## 6. The Greedy Encoder Loop (Not a Single Pass)

**This is the most common encoder implementation error.**

When encoding a text chunk, the encoder must repeatedly apply the best
available merge until no more ranked pairs exist in the current token
sequence. A single left-to-right pass is not BPE encoding.

**Correct algorithm:**

```
For each pre-tokenized chunk:
  1. Convert chunk to list of base byte token IDs (one per byte).
  2. Repeat:
     a. Find all adjacent pairs present in the current token list.
     b. Among those, find the pair with the lowest merge rank
        (i.e., the pair learned earliest during training).
     c. If no such pair exists (no pair in the list is in the merge table),
        stop — this chunk is fully encoded.
     d. Apply that pair non-overlapping left-to-right (per Rule 4).
  3. Emit the resulting token IDs.
```

**Why a single pass is wrong:** after merging `(a, b)` into `ab`, new
adjacent pairs may form (e.g., `(ab, c)` that was not adjacent before the
merge). A single pass misses these and produces incorrect, over-segmented
output that fails the roundtrip check.

```python
def encode_chunk(
    chunk_bytes: bytes,
    merge_rank: dict[tuple[int, int], int],  # pair → rank (0 = first learned)
) -> list[int]:
    tokens = list(chunk_bytes)               # base IDs = byte values
    while True:
        # find the best (lowest-rank) pair present in the current sequence
        best_pair: tuple[int, int] | None = None
        best_rank = float("inf")
        for i in range(len(tokens) - 1):
            pair = (tokens[i], tokens[i + 1])
            rank = merge_rank.get(pair)
            if rank is not None and rank < best_rank:
                best_rank = rank
                best_pair = pair
        if best_pair is None:
            break                            # no more ranked pairs — done
        new_id = 256 + best_rank             # merge ID assignment is deterministic
        tokens = apply_merge(tokens, best_pair, new_id)
    return tokens
```

**Relationship to merge rank:** the merge rank of a pair is its index in the
`merges` list (0-indexed). The corresponding token ID is `256 + rank`. The
encoder uses rank to select which merge to apply first, which mirrors the
order in which pairs were learned during training.

---

## Quick Reference: Common Failure Modes

| Symptom                                               | Likely Cause                                                   |
| ----------------------------------------------------- | -------------------------------------------------------------- |
| Deterministic fixture test fails with wrong merge IDs | Tie-breaking uses `max()` or dict order instead of `min()`     |
| Fixture test fails with subtly different merge count  | Chunk boundary not enforced; cross-boundary pair got merged    |
| `decode(encode(text)) != text` for multi-byte Unicode | Encoder loop is a single pass; multi-step merges not applied   |
| `decode(encode(text)) != text` for `[a,a,a]` input    | Overlapping merge applied; `[1,1,1]` invariant violated        |
| Training produces extra merges on empty-ish corpus    | Early stop check missing; continues after pair_counts is empty |
| Special token ID is wrong                             | `vocab_size` miscounted to include special token               |

---

## File Responsibilities

| File                      | Rules that apply                                                                                           |
| ------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `_constants.py`           | Canonical regex, schema version 1, `<\|endoftext\|>` literal                                               |
| `_pretokenizer.py`        | Produces chunk list; boundaries defined here                                                               |
| `_trainer.py`             | Rules 1, 2, 3, 4, 5                                                                                        |
| `_encoder.py`             | Rules 2, 4, 6                                                                                              |
| `_persistence.py`         | Stores `merges` list in learned order; loader must reconstruct `merge_rank` dict                           |
| `tests/test_trainer.py`   | Must cover tie-breaking with crafted corpus, `[1,1,1]` invariant, early stop, chunk boundary negative case |
| `tests/test_roundtrip.py` | Must cover multi-byte Unicode, emoji, CJK — these stress-test the encoder loop                             |
