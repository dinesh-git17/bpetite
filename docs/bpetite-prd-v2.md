# bpetite - Product Requirements Document

**Version:** v3.0 - Handoff Ready  
**Owner:** Dinesh  
**Last Updated:** April 7, 2026  
**Status:** Ready for engineering handoff  
**Repository:** `bpetite`

---

## Title

`bpetite` v1.0 - Deterministic Byte-Level BPE Tokenizer from Scratch

## Document Status

Ready for engineering handoff.

## Owner(s)

- Dinesh - product and engineering owner

## Last Updated

April 7, 2026

## Summary

`bpetite` is a local Python library and CLI that implements a deterministic byte-level BPE tokenizer from scratch for learning and portfolio demonstration purposes. The v1 deliverable trains on UTF-8 text using a GPT-2-style pre-tokenizer, encodes and decodes text losslessly, persists a versioned tokenizer artifact to disk, reloads it with byte-for-byte fidelity, and exposes a small public API plus a usable CLI.

This project is explicitly educational and local-only. It is not a production tokenizer service and does not target production-scale corpora.

## Problem Statement

Most engineers use tokenizers as opaque dependencies and cannot reason about their behavior, data model, or failure modes. That is acceptable for application usage but weak for foundational ML engineering. `bpetite` exists to make the tokenization layer understandable in executable code, with deterministic behavior, explicit tests, and engineering quality high enough that a senior reviewer can inspect the repository and see real understanding rather than a toy script.

## Goals

- Implement a correct byte-level BPE tokenizer in pure Python with deterministic training behavior.
- Guarantee `decode(encode(text)) == text` for all supported inputs, including empty strings, whitespace-only strings, Unicode text, and the reserved special token literal.
- Provide a stable, versioned single-file tokenizer artifact that can be saved and loaded without behavioral drift.
- Expose a minimal public API and a CLI that a first-time reviewer can run locally without follow-up clarification.
- Enforce repo quality with typed code, linting, tests, and CI.

## Non-Goals

- Exact token ID parity with GPT-2 or `tiktoken`.
- Production-scale training, serving, or optimization for large corpora.
- Support for WordPiece, Unigram, SentencePiece, or transformer model training.
- A web app, REST API, hosted service, or mobile client.
- PyPI publication in v1.

## Scope

- In scope: byte-level BPE training, encoding, decoding, persistence, one reserved special token, local CLI, tests, CI, benchmark documentation, and README documentation.
- In scope: training on UTF-8 text supplied via local file or in-memory string.
- In scope: TinyShakespeare as the demo corpus and small in-repo fixtures for deterministic tests.
- In scope: optional `tiktoken` side-by-side comparison as a reference-only utility after launch-critical work is complete.
- Out of scope: network behavior in the core library, model inference, distributed training, or performance tuning beyond basic local usability.

## User Types / Actors

- Primary actor: Dinesh, as the developer and learner.
- Secondary actor: technical reviewers reading the repository and running the CLI locally.
- System actor: CI, which validates tests, types, and formatting on every change.

## Assumptions

- All training and encode/decode input is valid Python `str` data in memory or UTF-8 text on disk.
- No Unicode normalization, case folding, or prefix-space insertion is applied anywhere in the pipeline.
- Python 3.12 is the supported interpreter for v1.
- The demo corpus is small enough to fit comfortably in memory on a developer laptop.
- The literal reserved special token for v1 is exactly `<|endoftext|>`.

## Constraints

- Core algorithm implementation must be pure Python; no Rust bindings, no C extensions, no external tokenizer libraries in the implementation path.
- The only runtime dependency beyond the standard library is `regex`.
- `vocab_size` refers only to mergeable vocabulary size and excludes reserved special tokens.
- The artifact format must be a single JSON file.
- Supported platforms for v1 are macOS and Linux. Windows is not a supported execution target for the provided shell scripts.

## Dependencies

- `regex` for Unicode-aware pre-tokenization.
- `pytest` for tests.
- `ruff` for linting and formatting.
- `mypy` for type checking.
- `uv` for environment and dependency management, with committed lockfile.
- GitHub Actions for CI.
- Optional dev-only dependency: `tiktoken` for comparison tooling.
- External demo corpus: TinyShakespeare download URL used only by the download helper script.

## Functional Requirements

### Package and Structure

- FR-1: Package code lives under `src/bpetite/`. Public imports are exposed from `src/bpetite/__init__.py`. Internal modules are not part of the public API contract.
- FR-2: The repository uses `pyproject.toml` as the source of package and tool configuration.
- FR-3: A reproducible dependency lockfile is committed and used for local setup and CI.

### Pre-tokenization

- FR-4: The pre-tokenizer compiles and uses this exact pattern with the `regex` package:

  ```python
  r"""'(?:[sdmt]|ll|ve|re)| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+"""
  ```

- FR-5: The pre-tokenizer returns chunks in source order and preserves all characters in the input exactly.
- FR-6: No normalization, case folding, prefix-space insertion, or whitespace trimming is applied before or after pre-tokenization.

### Training

- FR-7: The trainer applies the same pre-tokenizer used by the encoder. Pair counting and merges occur only within pre-tokenized chunk boundaries.
- FR-8: Training starts from exactly 256 base tokens, one per byte value `0..255`. Merge-derived token IDs are assigned sequentially starting at `256`.
- FR-9: Training input is `corpus: str` plus `vocab_size: int`. If `vocab_size < 256`, training raises `ValueError`. If `vocab_size == 256`, training returns the base vocabulary with zero merges.
- FR-10: At each merge iteration, the trainer selects the highest-frequency adjacent pair. Ties are broken by lexicographic tuple ordering in standard Python tuple comparison. Pair replacement is non-overlapping and left-to-right within each chunk.
- FR-11: If no mergeable pairs remain before the target `vocab_size` is reached, training stops early and returns the actual learned mergeable vocabulary size without error.
- FR-12: The trainer is deterministic. The same corpus bytes and same `vocab_size` under the same code revision must produce the same merges and same persisted artifact bytes.

### Special Tokens

- FR-13: After merge training completes, the tokenizer reserves `<|endoftext|>` as a special token at the first token ID greater than or equal to the final mergeable vocabulary size.
- FR-14: In v1, `<|endoftext|>` is the only reserved special token.
- FR-15: During encoding, the special token is never split by pre-tokenization or BPE merge application. During training, the corpus is pre-tokenized without special-token extraction — `<|endoftext|>` in training text is treated as ordinary characters. Special token reservation occurs after merge training completes.

### Encoding

- FR-16: `encode(text: str) -> list[int]` first extracts exact literal occurrences of `<|endoftext|>`, then pre-tokenizes the remaining text segments, converts each chunk to UTF-8 bytes, and applies learned merges by merge rank. Within each chunk, merge application iterates through the merge list in rank order; when a merge applies multiple times in a single pass, replacements are non-overlapping and left-to-right, matching the training-time replacement semantics. Returns token IDs.
- FR-17: `encode("")` returns `[]`.
- FR-18: Partial special token strings such as `<|endoftext` are treated as ordinary text.
- FR-19: Multiple consecutive special tokens encode as multiple special token IDs in order.

### Decoding

- FR-20: `decode(token_ids: Sequence[int]) -> str` maps each token ID to its bytes, concatenates all bytes, and decodes with UTF-8 strict mode.
- FR-21: `decode([])` returns `""`.
- FR-22: Unknown token IDs raise `KeyError`.
- FR-23: Invalid UTF-8 byte sequences raise `UnicodeDecodeError`.
- FR-24: Decoding a reserved special token ID returns the literal string `<|endoftext|>`.

### Roundtrip Correctness

- FR-25: `decode(encode(text)) == text` must hold for all supported inputs, including:
  - empty string
  - whitespace-only text
  - ASCII text
  - Unicode text including emoji, CJK, and Arabic
  - text containing one or more occurrences of `<|endoftext|>`

### Persistence

- FR-26: Persistence uses a versioned single-file JSON artifact and must preserve identical encode/decode behavior across save/load boundaries.
- FR-27: Saving to an existing path fails unless overwrite is explicitly requested.
- FR-28: Saves are atomic: write to a temporary file in the destination directory and then replace the final path.
- FR-29: Loading validates schema version, required keys, key shapes, merge shapes, token ID uniqueness, and byte ranges.

### Public API

- FR-30: The public API exposes exactly five methods: `train`, `encode`, `decode`, `save`, and `load`.
- FR-31: Internal modules are not covered by backward compatibility guarantees.

### CLI

- FR-32: The CLI exposes explicit subcommands: `train`, `encode`, `decode`, and optional `compare-tiktoken`.
- FR-33: CLI errors are written to `stderr` and return non-zero exit codes.
- FR-34: Machine-readable command results are written to `stdout`.
- FR-35: `compare-tiktoken` is informational only and is not a launch blocker.

### Quality Gates

- FR-36: The repository must pass:
  - `uv run pytest`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run mypy --strict`

- FR-37: Byte-handling code must satisfy strict byte typing semantics and must not rely on implicit coercions between `bytes`, `bytearray`, and `memoryview`.

## Detailed User Flows / System Flows

### Training Flow

1. User runs `bpetite train --input <path> --vocab-size <n> --output <path> [--force]`.
2. CLI reads the input file as UTF-8 with strict decoding and fails fast on invalid text.
3. Trainer pre-tokenizes the corpus into chunks using the canonical regex.
4. Each chunk is converted to a list of base byte token IDs.
5. Merge training runs until either the requested mergeable vocabulary size is reached or no further pairs exist.
6. `<|endoftext|>` is appended as a reserved special token after merge training.
7. Artifact is written atomically to disk.
8. CLI prints a summary containing corpus bytes, requested vocab size, actual mergeable vocab size, special token count, and elapsed time.

### Encode Flow

1. User calls `Tokenizer.encode(text)` or `bpetite encode --model <path> --text <text>`.
2. Exact literal occurrences of `<|endoftext|>` are extracted before pre-tokenization.
3. Non-special segments are pre-tokenized, converted to UTF-8 bytes, and greedily merged by learned rank.
4. Special token segments emit the reserved special token ID.
5. Output is returned as `list[int]` in the library and as a compact JSON array on `stdout` in the CLI.

### Decode Flow

1. User calls `Tokenizer.decode(ids)` or `bpetite decode --model <path> --ids <id...>`.
2. Each ID is resolved through the loaded vocabulary, including reserved special token IDs.
3. All bytes are concatenated in order and decoded with UTF-8 strict mode.
4. The library returns the decoded string.
5. The CLI writes raw decoded text to `stdout` and no additional wrapper text.

### Save / Load Flow

1. `save(path, overwrite=False)` validates path semantics and writes a versioned JSON artifact via temporary-file replace.
2. `load(path)` parses JSON, validates schema version and required keys, reconstructs vocab and merges, and rebuilds special-token lookup tables.
3. The loaded tokenizer must produce byte-for-byte identical encode/decode behavior to the original tokenizer.
4. Corrupt artifacts fail fast with typed exceptions and precise error messages.

### Reference Comparison Flow

1. User optionally runs `bpetite compare-tiktoken --model <path> --text <text>`.
2. CLI prints `bpetite` token IDs, token count, `tiktoken` token IDs, and token count side by side.
3. This command is reference-only and does not impose a parity requirement.

## Edge Cases and Failure Handling

- Empty corpus: valid; training returns base vocabulary plus reserved special token and zero merges.
- Corpus with no repeated adjacent pairs: valid; training stops early.
- `vocab_size < 256`: raise `ValueError`.
- Missing input file: CLI returns exit code `1` and prints the file error to `stderr`.
- Invalid UTF-8 input file: fail fast during file read; no replacement behavior.
- Empty string encode: return `[]`.
- Whitespace-only input: preserve whitespace and roundtrip exactly.
- Partial special token strings such as `<|endoftext`: treat as ordinary text.
- Multiple consecutive special tokens: encode as multiple special token IDs.
- Unknown token ID in decode: raise `KeyError`.
- Invalid concatenated bytes in decode: raise `UnicodeDecodeError`.
- Saving to an existing file without overwrite permission: raise `FileExistsError`.
- Saving to a path with a missing parent directory: raise `FileNotFoundError`.
- Loading JSON with missing keys: raise `KeyError`.
- Loading JSON with invalid value shapes or byte ranges: raise `ValueError`.

## Data / API / Integration Considerations

### Public API Contract

```python
from collections.abc import Sequence

class Tokenizer:
    @classmethod
    def train(cls, corpus: str, vocab_size: int) -> "Tokenizer": ...

    def encode(self, text: str) -> list[int]: ...

    def decode(self, token_ids: Sequence[int]) -> str: ...

    def save(self, path: str, overwrite: bool = False) -> None: ...

    @classmethod
    def load(cls, path: str) -> "Tokenizer": ...
```

### CLI Contract

```bash
uv run bpetite train --input data/sample.txt --vocab-size 512 --output tokenizer.json
uv run bpetite encode --model tokenizer.json --text "Hello world"
uv run bpetite decode --model tokenizer.json --ids 72 101 108 108 111
```

### Artifact Schema v1

```json
{
  "schema_version": 1,
  "mergeable_vocab_size": 258,
  "pretokenizer_pattern": "'(?:[sdmt]|ll|ve|re)| ?\\p{L}+| ?\\p{N}+| ?[^\\s\\p{L}\\p{N}]+|\\s+(?!\\S)|\\s+",
  "vocab": {
    "0": [0],
    "1": [1],
    "256": [116, 104],
    "257": [116, 104, 101],
    "258": [60, 124, 101, 110, 100, 111, 102, 116, 101, 120, 116, 124, 62]
  },
  "merges": [
    [116, 104],
    [256, 101]
  ],
  "special_tokens": {
    "<|endoftext|>": 258
  }
}
```

Note: `mergeable_vocab_size` equals `len(merges) + 256`. In this example, 2 merges yields `mergeable_vocab_size = 258`. The special token occupies the next available ID (`258`). Vocab values are always raw byte lists (each integer in `0..255`), not token IDs. Merge entries use token IDs: `[256, 101]` means "merge token 256 with byte-token 101". The resulting token 257 stores the concatenated bytes `[116, 104, 101]`. Key `258` is the reserved special token whose bytes are the UTF-8 encoding of `<|endoftext|>`.

### Additional Data Rules

- JSON vocab keys are decimal strings because JSON object keys cannot be integers.
- The saved vocabulary includes reserved special token IDs as byte sequences equal to the UTF-8 bytes of the literal special token string.
- The loader validates that every byte value is an integer in `0..255`.
- Tests live under `tests/` and import from the installed `src/` package path, not by mutating `PYTHONPATH`.

## Security / Privacy / Compliance Considerations

- Core library and CLI perform no network calls.
- The only networked helper is the corpus download script, which is outside the core runtime path.
- The project collects no telemetry, analytics, secrets, or user identifiers.
- Loader behavior is data-only JSON parsing; it must never evaluate code or import modules from the artifact.
- Dependency versions are locked for reproducibility.
- No additional compliance regime applies to this v1 local educational tool.

## Reliability / Performance Expectations

- Determinism is a release requirement: the same corpus bytes and same `vocab_size` must produce identical artifact bytes on repeated runs under the same code revision.
- Local development target: TinyShakespeare at `vocab_size=512` completes in `<= 60s` on the documented benchmark machine.
- Local encode target: a 50-word sentence encodes with `p99 < 100ms` over 100 runs on the documented benchmark machine.
- `vocab_size=32000` is a demo-only workload. It must complete correctly, but it is not a CI-gated latency target.
- Performance checks are documented in `README.md` or `docs/benchmarks.md`; they are release evidence, not unit tests.

## Observability / Analytics Requirements

- CLI writes progress updates during training at start, every 100 merges, and completion.
- CLI writes final elapsed time and actual learned mergeable vocab size.
- CLI writes machine-readable results only to `stdout` and all human-readable errors only to `stderr`.
- Library exceptions use precise, grep-friendly messages that match the actual failure condition.
- CI is the primary operational signal: test, lint, format, and type-check status must be visible on every change.
- No product analytics or telemetry are collected.

## Rollout Plan

### Phase 1 - Scaffolding and Project Setup

- Add `pyproject.toml`, lockfile, `src/bpetite/`, `tests/`, and CI.
- Configure CI on `ubuntu-latest` and `macos-latest` for Python 3.12.
- Add baseline tool configuration for `pytest`, `ruff`, and `mypy`.

**Exit gate:** repo structure exists, local environment is reproducible, and CI passes on an empty scaffold.

### Phase 2 - Pre-tokenizer, Trainer, and Persistence

- Implement pre-tokenizer with canonical regex.
- Implement deterministic training with early-stop handling.
- Implement versioned artifact save/load with validation and atomic writes.
- Add deterministic unit tests for merge order, tie-breaking, empty corpus, and artifact schema validation.

**Exit gate:** repeated training on the same fixture corpus produces byte-identical artifacts.

### Phase 3 - Encoder, Decoder, and Special Token Correctness

- Implement encoder and decoder.
- Implement reserved special token extraction and decoding.
- Add roundtrip tests for empty string, whitespace-only, ASCII, emoji, CJK, Arabic, punctuation, and special-token-containing text.

**Exit gate:** `decode(encode(text)) == text` passes for all required fixtures.

### Phase 4 - CLI, Documentation, and Demo Run

- Implement CLI subcommands: `train`, `encode`, and `decode`.
- Add automated CLI smoke tests.
- Add README usage and benchmark documentation.
- Run end-to-end demo training on TinyShakespeare.

**Exit gate:** first-time local reviewer can set up the repo and run the CLI without follow-up clarification.

### Phase 5 - Optional Reference Comparison

- Add optional `compare-tiktoken` CLI support.
- Document expected differences and the fact that exact parity is not a requirement.

**Exit gate:** reference comparison is usable and documented, with no change to launch-critical correctness requirements.

## Risks and Mitigations

| Risk                                                      | Likelihood | Impact | Mitigation                                                                                         |
| --------------------------------------------------------- | ---------- | ------ | -------------------------------------------------------------------------------------------------- |
| Pure-Python training is slow at larger vocab sizes        | High       | Medium | Keep `512` as the default dev target, document `32000` as demo-only, do not gate CI on 32k runtime |
| Divergence between training and encoding chunk boundaries | Medium     | High   | Enforce shared pre-tokenizer use and cover with deterministic tests                                |
| Artifact drift or corruption                              | Medium     | High   | Use schema versioning, loader validation, and atomic writes                                        |
| Unicode edge case bugs                                    | Medium     | High   | Require fixtures covering emoji, CJK, Arabic, whitespace-only, punctuation, and special tokens     |
| Platform drift                                            | Low        | Medium | Support macOS and Linux explicitly in CI and keep shell helpers out of the core runtime contract   |

## Acceptance Criteria

- The package exists under `src/bpetite/` and public imports resolve from `bpetite`.
- CI passes on Python 3.12 for tests, lint, format-check, strict typing, packaging build, CLI smoke, determinism, and policy guards. The `tests` and `cli-smoke` gates execute on both `ubuntu-latest` and `macos-latest` because they exercise runtime code paths that can legitimately drift across operating systems. The `lint`, `format`, `type`, `build`, `determinism`, `policy-guard`, and `syntax` gates execute on `ubuntu-latest` only because their underlying tools (`ruff`, `mypy`, `uv build`, `py_compile`, AST-based policy scripts) are OS-invariant by construction and a second OS run would consume Actions minutes without catching additional regressions.
- Training on the same corpus twice produces byte-identical tokenizer artifacts.
- The trainer never merges across pre-tokenizer chunk boundaries.
- `decode(encode(text)) == text` passes for fixtures covering empty string, whitespace-only, ASCII, emoji, CJK, Arabic, mixed punctuation, and text containing `<|endoftext|>`.
- `encode("") == []` and `decode([]) == ""`.
- `vocab_size < 256` raises `ValueError`; unknown token IDs raise `KeyError`; invalid decoded bytes raise `UnicodeDecodeError`.
- Save/load preserves identical encode/decode outputs for all roundtrip fixture inputs.
- CLI smoke tests cover `train`, `encode`, and `decode` on a small fixture corpus.
- Saving without overwrite permission fails; saving with overwrite succeeds atomically.
- `README.md` documents setup, commands, limits, benchmark machine, and the fact that exact GPT-2 parity is not a goal.

## Open Questions

None.
