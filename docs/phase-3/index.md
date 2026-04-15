---
title: Phase 3 — Encode, Decode, and Public API
description: Reading guide and vocabulary reference for the bpetite Phase 3 implementation.
slug: phase-3-index
order: 20
category: Phase 3
published: true
---

# Phase 3 — Encode, Decode, and Public API

Phase 3 delivers the public surface of bpetite: the encoder that turns text
into token ids, the decoder that turns token ids back into text, the public
`Tokenizer` class that wires all four Phase 2 and Phase 3 modules behind a
five-method contract, and the roundtrip suite that proves
`decode(encode(text)) == text` through the public API only.

## TL;DR

- The encoder extracts reserved special tokens by exact literal match,
  pre-tokenizes the remaining segments, and applies learned merges in rank
  order with single non-overlapping LTR passes (FR-16 through FR-19).
- The decoder is one expression: concatenate token bytes from the vocab,
  then decode once with UTF-8 strict mode, propagating `KeyError` and
  `UnicodeDecodeError` unchanged (FR-20 through FR-24).
- Three area docs (`encode-decode`, `public-api`, `roundtrip-suite`) each
  stand alone; this index is the entry point and the single place where new
  Phase 3 vocabulary terms are defined.

## What lives here

### Phase 3 documentation

| Doc                                   | Slug                      | What you learn                                                                                                                                                        |
| ------------------------------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Encode and Decode](encode-decode.md) | `phase-3-encode-decode`   | Special-token extraction, per-rank non-overlapping merge application, strict UTF-8 decode; worked example tracing `encode("ab<\|endoftext\|>ab")` end-to-end and back |
| [Public Tokenizer API](public-api.md) | `phase-3-public-api`      | The five-method contract, private instance state, classmethod factories, delegation-only implementation, and the `__init__.py` single-export rule                     |
| [Roundtrip Suite](roundtrip-suite.md) | `phase-3-roundtrip-suite` | The 55-test suite that proves FR-17–FR-26 against the public API, the two shared fixtures, and the `decode([0x80])` UnicodeDecodeError construction                   |

### Phase 3 source modules

| Module                      | Task | Role                                                                                                                      |
| --------------------------- | ---- | ------------------------------------------------------------------------------------------------------------------------- |
| `src/bpetite/_encoder.py`   | 3-1  | `encode` — special-token extraction, pre-tokenization, per-rank non-overlapping merge application                         |
| `src/bpetite/_decoder.py`   | 3-2  | `decode` — byte concatenation then strict UTF-8 decode; one expression, no branching                                      |
| `src/bpetite/_tokenizer.py` | 3-3  | `Tokenizer` class — delegation-only facade wrapping trainer, encoder, decoder, and persistence behind five public methods |
| `src/bpetite/__init__.py`   | 3-3  | `from bpetite._tokenizer import Tokenizer`; `__all__ = ["Tokenizer"]` — the single public export                          |
| `tests/test_roundtrip.py`   | 3-4  | 55-test public-API suite covering FR-17 through FR-26 and the save/load parity run                                        |
| `tests/conftest.py`         | 3-4  | Session-scoped `trained_tokenizer` fixture shared across the roundtrip suite                                              |

## Key invariants

These invariants cut across all three Phase 3 areas. Each area doc covers
its own FR-keyed invariant table in full detail.

| FR                       | Invariant                                                                                                                                                     | Area                                  |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| FR-16                    | The encoder extracts exact literal special tokens first, pre-tokenizes remaining segments, then applies merges in rank order with non-overlapping LTR passes. | Encode and Decode                     |
| FR-18                    | Partial special strings such as `<\|endoftext` and `endoftext\|>` are treated as ordinary text and must roundtrip unchanged.                                  | Encode and Decode                     |
| FR-20                    | The decoder concatenates token bytes then decodes once with UTF-8 strict mode; `KeyError` and `UnicodeDecodeError` propagate unchanged.                       | Encode and Decode                     |
| FR-24                    | Decoding the reserved special-token id returns the literal string `<\|endoftext\|>` via a vocab entry storing the literal's UTF-8 bytes.                      | Encode and Decode                     |
| FR-25                    | `decode(encode(text)) == text` for every supported input class, through the live tokenizer and through the save/load boundary.                                | Roundtrip Suite + Phase 2 Persistence |
| PRD §Public API Contract | The public surface is exactly five methods on `Tokenizer`: `train`, `encode`, `decode`, `save`, `load`; `Tokenizer` is the only public name on `bpetite`.     | Public API                            |

## Walkthrough

### Recommended reading order

A portfolio reviewer with no prior context can cover Phase 3 in three
passes:

1. **[Encode and Decode](encode-decode.md)** — Start here. Read the encode
   pipeline diagram and the worked example (`train_bpe("ab ab ab", 258)`
   then `encode("ab<|endoftext|>ab")`). This is the algorithmic heart of
   Phase 3. Budget 5–6 minutes.
2. **[Public Tokenizer API](public-api.md)** — Read the signature block,
   the end-to-end session, and the delegation-not-reimplementation
   section. Skim the failure modes table on a first pass. Budget 3–4
   minutes.
3. **[Roundtrip Suite](roundtrip-suite.md)** — Skim. The 15 parametrized
   cases table, the two-fixture design, and the `[0x80]` construction
   are the only non-obvious points. Budget 2 minutes.

A future contributor adding a feature or fixing a bug in Phase 3 should
read the relevant area doc in full, including the failure modes table,
before touching any Phase 3 source file.

### Phase 3 in one paragraph

The encoder extracts reserved special tokens from the input by exact
literal match, pre-tokenizes each remaining text segment into UTF-8 byte
chunks via the canonical regex, and applies the learned merges in rank
order — at each rank, a single non-overlapping left-to-right pass replaces
every adjacent match in the chunk. The decoder is a single expression:
look each token id up in the vocab, concatenate the bytes, decode once
with UTF-8 strict mode. The public `Tokenizer` class wraps the trainer,
encoder, decoder, and persistence layer behind five methods whose
signatures match PRD lines 254–269 exactly; every method is a one-line
delegation to a private module, so the class body holds no algorithmic
logic. The roundtrip suite proves that
`decode(encode(text)) == text` for fifteen input classes (empty,
whitespace, ASCII, emoji, CJK, Arabic, mixed punctuation, the literal
`<|endoftext|>` in three configurations, three partial-special variants),
and the same fifteen cases are re-run against a saved-and-reloaded
tokenizer to prove the save/load boundary preserves encode output
byte-for-byte (FR-26).

### Vocabulary reference

Phase 2 locked the project-wide vocabulary in
[`docs/phase-2/index.md`](../phase-2/index.md#vocabulary-reference). Phase 3
introduces three new locked terms used identically across all Phase 3
docs. Using a synonym for a locked term is a bug, not a style choice.

| Term                       | Definition                                                                                                                                                                                                      |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `segment`                  | A span of input text between reserved-special-token occurrences, or the whole input when no specials exist. Segments are pre-tokenized into chunks; they are not themselves chunks.                             |
| `special-token extraction` | The exact-literal matching pass the encoder performs before pre-tokenization, isolating reserved special tokens from ordinary text. Partial strings are never extracted; the match must equal the full literal. |
| `roundtrip invariant`      | The FR-25 guarantee that `decode(encode(text)) == text` for every supported input class, through both the live `Tokenizer` instance and the save/load boundary.                                                 |

## Failure modes

The four silent failure modes that Phase 3 docs call out by name. Each
fails quietly under most tests and is caught only by the specific
assertion listed.

| Failure                                                                       | Silent because                                                                                                                | Caught by                                                                             | Doc                                   |
| ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------- |
| Single-match-per-rank encoder bug                                             | Inputs with one match per ranked pair still roundtrip; only multi-match inputs expose divergence from training-time semantics | `tests/test_roundtrip.py::test_roundtrip[<label>-...]` on any multi-match case        | [Encode and Decode](encode-decode.md) |
| Partial-special false match                                                   | Inputs without partial specials roundtrip fine; only the three partial-special test cases expose it                           | `tests/test_roundtrip.py::test_roundtrip[partial special prefix\|suffix\|short-...]`  | [Encode and Decode](encode-decode.md) |
| Decoder uses `errors="replace"` instead of `errors="strict"`                  | Valid inputs still roundtrip; only the lone continuation byte test exposes it                                                 | `tests/test_roundtrip.py::test_decode_invalid_utf8_raises`                            | [Encode and Decode](encode-decode.md) |
| `Tokenizer.encode` reads a stored `self._text` instead of the method argument | One call still returns the correct ids; only two consecutive calls with different inputs expose it                            | No dedicated automated test — code-level constraint at `src/bpetite/_tokenizer.py:78` | [Public Tokenizer API](public-api.md) |

## Related reading

- [Phase 2 Index](../phase-2/index.md) — the core algorithm, persistence
  layer, and fixture set that Phase 3 delegates to; the project-wide
  vocabulary lock defined there is in force throughout Phase 3.
- [Phase 2 Core Algorithm](../phase-2/core-algorithm.md) — the training
  contract that `Tokenizer.train` wraps; the tie-breaking and
  non-overlapping merge semantics the encoder mirrors at inference time.
- [Phase 2 Persistence](../phase-2/persistence.md) — the atomic save and
  strict validating load that `Tokenizer.save` and `Tokenizer.load`
  delegate to, and the save/load parity the roundtrip suite proves
  through the public API.
- [`docs/bpetite-prd-v2.md`](../bpetite-prd-v2.md) — FR-16 through FR-26
  (encode, decode, roundtrip, save/load parity); §Public API Contract,
  lines 254–269.
- [`src/bpetite/`](../../src/bpetite/) — Phase 3 source modules.
- [`tests/test_roundtrip.py`](../../tests/test_roundtrip.py) — the
  Phase 3 test suite.
