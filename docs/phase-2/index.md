---
title: Phase 2 — Core Algorithm, Fixtures, and Persistence
description: Reading guide and vocabulary reference for the bpetite Phase 2 implementation.
slug: phase-2-index
order: 10
category: Phase 2
published: true
---

# Phase 2 — Core Algorithm, Fixtures, and Persistence

Phase 2 delivers the three components that make bpetite a working, reproducible tokenizer:
a deterministic byte-level BPE trainer, a versioned artifact format with a strict loader, and
a fixed test fixture set that anchors the suite to byte-exact expected outputs.

## TL;DR

- The trainer converts raw text to a merge list deterministically: same corpus, same
  `vocab_size`, same code revision → identical artifact bytes, every time.
- The persistence layer serializes the trained state to a single versioned JSON file with
  atomic writes and a 19-step loader that rejects every class of corrupt artifact.
- Three area docs (D2, D3, D4) each stand alone; this index is the entry point and the
  single place where vocabulary terms are defined.

## What lives here

### Phase 2 documentation

| Doc                                                  | Slug                     | What you learn                                                                                                                          |
| ---------------------------------------------------- | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| [Core Algorithm](core-algorithm.md)                  | `phase-2-core-algorithm` | Pre-tokenizer regex, pair counting with corpus multiplicity, tie-breaking, non-overlapping merge, early stop, special-token reservation |
| [Persistence and Artifact Schema v1](persistence.md) | `phase-2-persistence`    | Field-by-field artifact schema, atomic save rationale, 19-step loader checklist, two determinism gates                                  |
| [Test Fixtures](fixtures.md)                         | `phase-2-fixtures`       | Per-fixture purpose and byte invariants, whitespace-preservation rule, `tiny.txt` → `trained_state` reproducibility chain               |

### Phase 2 source modules

| Module                         | Task | Role                                                                                                                   |
| ------------------------------ | ---- | ---------------------------------------------------------------------------------------------------------------------- |
| `src/bpetite/_constants.py`    | 2-1  | Canonical regex pattern, schema version, special-token literal — single source of truth for values that must not drift |
| `src/bpetite/_pretokenizer.py` | 2-2  | GPT-2-style pre-tokenizer; compiles the pattern once at import time                                                    |
| `src/bpetite/_trainer.py`      | 2-3  | Deterministic BPE trainer; produces `TrainerResult` with merges, vocab, and special-token reservation                  |
| `src/bpetite/_persistence.py`  | 2-4  | Atomic `save()` and validating `load()` for Artifact Schema v1                                                         |

## Key invariants

These invariants cut across all three Phase 2 areas. Each area doc covers its own FR-keyed
invariant table in full detail.

| FR    | Invariant                                                                                                         | Area                         |
| ----- | ----------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| FR-12 | The same `(corpus, vocab_size)` always produces byte-identical artifact output.                                   | Core Algorithm + Persistence |
| FR-7  | Pair counting and merge application are bounded by pre-tokenizer chunk boundaries; pairs never bridge chunks.     | Core Algorithm               |
| FR-10 | Ties in pair frequency are broken by lexicographic tuple ordering: `min(..., key=lambda item: (-count, pair))`.   | Core Algorithm               |
| FR-28 | Saves are atomic: a temp file in `dest.parent` is written first, then renamed into place.                         | Persistence                  |
| FR-29 | The loader validates schema version, required keys, shapes, ranges, and cross-field constraints before returning. | Persistence                  |

## Walkthrough

### Recommended reading order

A portfolio reviewer with no prior context can cover Phase 2 in three passes:

1. **[Core Algorithm](core-algorithm.md)** — Start here. Read the two-phase training model
   diagram, the tie-breaking section, and the worked example
   (`train_bpe("ab ab ab", vocab_size=258)`). This is the algorithmic heart of the project.
   Budget 5–6 minutes.

2. **[Persistence and Artifact Schema v1](persistence.md)** — Read the field-by-field schema
   table and the atomic save diagram. The loader validation checklist (19 steps) and the two
   determinism gates are the most technically dense section; skim them on a first pass. Budget
   4–5 minutes.

3. **[Test Fixtures](fixtures.md)** — Skim. The whitespace-preservation rule and the
   `tiny.txt` → `trained_state` chain are the only non-obvious points. Budget 2 minutes.

A future contributor adding a feature or fixing a bug should read the relevant area doc in
full, including the failure modes table, before touching any Phase 2 source file.

### Phase 2 in one paragraph

The pre-tokenizer splits input text into chunks using a single centralized GPT-2-style regex
and encodes each chunk as UTF-8 bytes. The trainer counts adjacent byte-pair frequencies
within each chunk (never across boundaries), selects the most frequent pair (ties broken
lexicographically), replaces it non-overlappingly left-to-right, and repeats until the
`vocab_size` quota is met or no pairs remain. The reserved special token
`<|endoftext|>` is assigned the first ID past the learned mergeable range after training
completes. The resulting state — merge list, vocabulary, special-token mapping — is
serialized to a single JSON artifact with `sort_keys=True` and compact separators, making
the output byte-deterministic. The loader re-validates every field, cross-checks every
derived value, and rejects artifacts with missing, extra, or malformed content before
returning the in-memory state.

### Vocabulary reference

These terms are used with the exact meanings defined here throughout all Phase 2 docs. Using
a synonym for a locked term is a bug, not a style choice.

| Term                     | Definition                                                                                                                                                                                        |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `vocab_size`             | The requested target mergeable vocabulary size, passed as an argument to `train_bpe`. Excludes reserved special tokens. Must be >= 256.                                                           |
| `mergeable_vocab_size`   | The actual learned mergeable vocabulary size after training: `256 + len(merges)`. May be smaller than `vocab_size` if early stop fired. Also the ID assigned to the first reserved special token. |
| `merge rank`             | The zero-based index of a merge in the merge list. Rank 0 corresponds to token ID 256, rank 1 to token ID 257, and so on.                                                                         |
| `pre-tokenizer`          | The regex-based function that splits input text into chunks before byte-level BPE is applied. Implemented in `_pretokenizer.py`; uses the pattern from `_constants.py`.                           |
| `chunk`                  | A single match produced by the pre-tokenizer regex, encoded as UTF-8 bytes. Pairs never bridge chunks.                                                                                            |
| `base byte`              | One of the 256 tokens with IDs 0–255, each representing a single byte value. The starting vocabulary before any merges. `vocab[i] == bytes([i])` for all base-byte IDs.                           |
| `reserved special token` | A token outside the mergeable range, assigned an ID >= `mergeable_vocab_size`. In v1, exactly one: `<\|endoftext\|>` at ID `mergeable_vocab_size`.                                                |

## Failure modes

The three silent failure modes that Phase 2 docs call out by name. Each fails quietly under
most tests and is caught only by the specific test listed.

| Failure                                | Silent because                                                                                                           | Caught by                                                                              | Doc                                 |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- | ----------------------------------- |
| Wrong tie-break ordering               | Any corpus where the lex-first pair also has the highest count will pass; only a deliberately constructed tie exposes it | `tests/test_trainer.py::test_train_tie_breaking_picks_lexicographically_smallest_pair` | [Core Algorithm](core-algorithm.md) |
| Missing `sort_keys=True` in serializer | A single save and load round-trips correctly; only comparing two saves of the same state exposes byte divergence         | `tests/test_persistence.py::test_same_state_saved_twice_produces_identical_bytes`      | [Persistence](persistence.md)       |
| Cross-device temp-file atomic replace  | Only surfaces at runtime on network or cross-device mounts; no local test can reproduce it                               | No automated test — code-level constraint in `_persistence.py:107`                     | [Persistence](persistence.md)       |

## Related reading

- [`docs/bpetite-prd-v2.md`](../bpetite-prd-v2.md) — FR-4 through FR-15 (core algorithm),
  FR-26 through FR-29 (persistence), FR-12 (determinism)
- [`src/bpetite/`](../../src/bpetite/) — Phase 2 source modules
- [`tests/`](../../tests/) — test suite
