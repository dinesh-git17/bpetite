---
title: Phase 4 — CLI, Presentation, Tests, and Benchmark Harness
description: Reading guide and vocabulary reference for the bpetite Phase 4 implementation.
slug: phase-4-index
order: 30
category: Phase 4
published: true
---

# Phase 4 — CLI, Presentation, Tests, and Benchmark Harness

Phase 4 delivers the public-facing surface of bpetite: the `train`, `encode`, and
`decode` command-line interface; the Rich-based presentation layer that renders every
human-readable element; the subprocess-level contract tests that enforce the stdout/stderr
channel boundary; and the encode-latency benchmark harness that produces the numbers
published on the Reference benchmarks page.

## TL;DR

- The CLI routes every machine-readable result to stdout and every human-readable
  element to stderr. The contract is enforced by subprocess tests that capture both
  streams and assert strict separation, and it is structurally reinforced by a single
  shared Rich `Console` constructed with `stderr=True` (FR-33, FR-34).
- The train progress surface is three plain `console.print` lifecycle lines emitted by a
  callback threaded through internal `train_bpe`, not through public `Tokenizer.train`.
  FR-30 pins the public method signature to `(corpus, vocab_size)` exactly, so the CLI
  calls `train_bpe` directly with the callback and wraps the result in a `Tokenizer`.
- Three area docs (`cli-contract`, `rich-presentation`, `benchmark-harness`) each stand
  alone; this index is the entry point and the single place where new Phase 4 vocabulary
  terms are defined. Baseline benchmark results are published separately on the Reference
  page at [`benchmarks`](../benchmarks.md).

## What lives here

### Phase 4 documentation

| Doc                                             | Slug                        | What you learn                                                                                                                                                                                                                                   |
| ----------------------------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [CLI Contract](cli-contract.md)                 | `phase-4-cli-contract`      | Channel discipline, exit code taxonomy, exact JSON output shapes for `train`/`encode`/`decode`, argparse patterns, progress-callback wiring through `ProgressEvent`, and the subprocess-level test harness that enforces the entire contract.    |
| [Rich Presentation Layer](rich-presentation.md) | `phase-4-rich-presentation` | Shared stderr `Console`, themed palette, panel helpers (`render_banner`, `render_kv_box`, `render_error`), the `is_fully_interactive` gate, and the design decision to use plain `console.print` lifecycle lines instead of a live Progress bar. |
| [Benchmark Harness](benchmark-harness.md)       | `phase-4-benchmark-harness` | `scripts/bench_encode.py` design, nearest-rank percentile math, the defensive 50-word sentence check, and the `elapsed_ms` trainer span vs command wall clock distinction.                                                                       |

### Phase 4 source, script, and test surface

| File                         | Task | Role                                                                                                                                    |
| ---------------------------- | ---- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `src/bpetite/_cli.py`        | 4-1  | `main`, three subcommand handlers, argparse setup, error routing, progress-callback wiring, and every stdout write                      |
| `src/bpetite/_ui.py`         | 4-1  | Shared stderr `Console`, themed palette, `render_banner`, `render_kv_box`, `render_error`, and `is_fully_interactive`                   |
| `src/bpetite/_banner.txt`    | 4-1  | ASCII art rendered by `render_banner` when the terminal allows it; loaded at call time, not at import                                   |
| `tests/test_cli.py`          | 4-2  | Subprocess-level contract tests covering every happy path, every runtime failure mode, and strict channel separation                    |
| `scripts/download_corpus.py` | 4-3  | TinyShakespeare fetcher that writes the corpus to `data/tinyshakespeare.txt` (.gitignore'd); the only network-touching code in the repo |
| `scripts/bench_encode.py`    | 4-4  | Encode-latency benchmark harness; reports `p50` (median) and `p99` (nearest-rank) over 100 runs of a fixed 50-word sentence             |
| `README.md`                  | 4-5  | Installation, locked setup, CLI examples with captured outputs, benchmark summary table, limits and non-goals                           |
| `docs/benchmarks.md`         | 4-4  | Baseline encode-latency and training-time measurements on the reference benchmark machine; companion to the harness design doc          |

## Key invariants

These invariants cut across all three Phase 4 areas. Each area doc covers its own
FR-keyed invariant table in full detail.

| FR                           | Invariant                                                                                                                                                                       | Area              |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| FR-33                        | CLI errors are written to `stderr` and return non-zero exit codes.                                                                                                              | CLI Contract      |
| FR-34                        | Machine-readable command results are written to `stdout`.                                                                                                                       | CLI Contract      |
| FR-30                        | The public API exposes exactly five methods on `Tokenizer`: `train`, `encode`, `decode`, `save`, `load`. The `train` progress callback cannot change this signature.            | CLI Contract      |
| FR-32                        | The CLI exposes explicit subcommands: `train`, `encode`, and `decode` (plus optional `compare-tiktoken` in Phase 5).                                                            | CLI Contract      |
| FR-36                        | The repository passes `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy --strict` on a clean clone.                                      | Release Gate      |
| PRD §Quality and Performance | TinyShakespeare at `vocab_size=512` completes in `<= 60s` on the documented benchmark machine; a 50-word sentence encodes with `p99 < 100ms` over 100 runs on the same machine. | Benchmark Harness |

## Walkthrough

### Recommended reading order

A portfolio reviewer with no prior context can cover Phase 4 in three passes:

1. **[CLI Contract](cli-contract.md)** — Start here. Read the channel discipline section,
   the `train` worked example end-to-end, and the progress-callback wiring block. This is
   the load-bearing surface every downstream user of bpetite touches. Budget 6–7 minutes.
2. **[Rich Presentation Layer](rich-presentation.md)** — Read the shared `Console`
   section, the themed palette table, and the "why not `rich.progress.Progress`" design
   decision block. Skim the panel helpers on a first pass. Budget 4 minutes.
3. **[Benchmark Harness](benchmark-harness.md)** — Read the nearest-rank percentile
   section and the `elapsed_ms` vs command wall clock distinction. The rest is
   reference-grade for anyone re-running or extending the harness. Budget 3 minutes.

A future contributor adding a CLI feature, a new subcommand, or a second benchmark
should read the relevant area doc in full, including the failure modes table, before
touching any Phase 4 source file.

### Phase 4 in one paragraph

The CLI is a thin argparse dispatcher over three subcommand handlers. Each handler reads
its inputs, delegates algorithmic work to the Phase 2 and Phase 3 modules through the
public `Tokenizer` class (or through internal `train_bpe` when the train subcommand needs
to attach a progress callback), and writes a machine-readable result to stdout. Every
banner, configuration panel, progress line, and error panel is rendered through a single
Rich `Console` instance constructed with `stderr=True`, so no styled bytes can leak into
the stdout contract. The subprocess-level contract tests in `tests/test_cli.py` invoke
the installed entry point via `subprocess.run`, not direct Python imports, so
stdout/stderr separation is preserved and every failure mode — missing input, invalid
UTF-8, save without `--force`, unknown decode id, malformed model artifact — is pinned
with an explicit test. The benchmark harness in `scripts/bench_encode.py` is standalone:
it imports only the public `Tokenizer`, encodes a fixed 50-word sentence 100 times
against a saved artifact, and reports `p50` via `statistics.median` and `p99` via
nearest-rank on the sorted samples. The timer field `elapsed_ms` in the `train` JSON
summary wraps only the internal `_train_with_progress` call and is explicitly documented
as a trainer span rather than a command wall clock.

### Vocabulary reference

Phase 2 locked the core project vocabulary in
[`docs/phase-2/index.md`](../phase-2/index.md#vocabulary-reference), and Phase 3 added
three encode/decode terms in
[`docs/phase-3/index.md`](../phase-3/index.md#vocabulary-reference). Phase 4 introduces
six new locked terms used identically across all Phase 4 docs. Using a synonym for a
locked term is a bug, not a style choice.

| Term                                   | Definition                                                                                                                                                                                                                                                                                                                                                                |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `channel discipline`                   | The load-bearing rule that every machine-readable CLI result goes to `stdout` only and every human-readable element goes to `stderr` only. Enforced by subprocess-level contract tests that capture both streams and assert the boundary.                                                                                                                                 |
| `machine-readable result`              | The subcommand's one-line stdout payload. For `train`, a JSON object with five required keys. For `encode`, a compact JSON array of token ids. For `decode`, the raw decoded text with no trailing newline.                                                                                                                                                               |
| `human-readable element`               | Every stderr render: the banner, configuration panel, training lifecycle lines, completion panel, and error panel. All routed through the shared `_ui.py` `Console`.                                                                                                                                                                                                      |
| `progress lifecycle event`             | One of the three `ProgressEvent` kinds the internal `train_bpe` emits: `"start"` once before the merge loop, `"merge"` every 100 completed merges, and `"complete"` once after the loop exits (including early-stop).                                                                                                                                                     |
| `nearest-rank percentile`              | The percentile variant used by the encode-latency harness: sort the samples ascending, return `sorted[ceil(p/100 * N) - 1]`. Distinct from `numpy.percentile`'s linear-interpolation default. For p99 with N=100, this is `sorted[98]`.                                                                                                                                   |
| `trainer span` vs `command wall clock` | Two distinct timings produced by the `train` subcommand. The **trainer span** is `elapsed_ms` in the JSON summary, wrapping only `_train_with_progress` at `_cli.py:112-114`. The **command wall clock** is the full shell-visible `time(1)` total, which additionally includes file I/O, argparse, Python startup, and the atomic save. The two are not interchangeable. |

## Failure modes

The four silent failure modes that Phase 4 docs call out by name. Each fails quietly
under most tests and is caught only by the specific assertion listed.

| Failure                                                       | Silent because                                                                                                                                               | Caught by                                                                                                            | Doc                                       |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Machine-readable JSON leaks onto stderr                       | The stdout payload still parses correctly in isolation; only a test that additionally asserts stderr is empty (or does not contain the JSON keys) catches it | `tests/test_cli.py::test_train_success_writes_json_summary_on_stdout`                                                | [CLI Contract](cli-contract.md)           |
| Every-100-merges progress branch never fires                  | Any vocab size that completes fewer than 100 merges skips the mid-training callback entirely; no ordinary fixture is large enough to hit the branch          | `tests/test_cli.py::test_train_progress_emits_every_100_merges_on_stderr` (deterministic 15 KB synthetic corpus)     | [CLI Contract](cli-contract.md)           |
| `"Training complete"` substring matches two rendered surfaces | The panel title and the `complete` lifecycle line both contain the substring; deleting the lifecycle line does not fail a bare-substring assertion           | Uniquely anchored `"Training complete: merges="` substring in `test_train_progress_emits_every_100_merges_on_stderr` | [CLI Contract](cli-contract.md)           |
| `elapsed_ms` mislabeled as command wall clock                 | The JSON field itself is correct; only a reader comparing it against outer `time(1)` across runs notices the scope mismatch                                  | Explicit scope note at `docs/benchmarks.md` and the trainer-span definition in this doc's vocabulary reference       | [Benchmark Harness](benchmark-harness.md) |

## Related reading

- [Phase 3 Index](../phase-3/index.md) — the public `Tokenizer` class the CLI wraps; the
  five-method contract that `train`, `encode`, and `decode` delegate to.
- [Phase 2 Index](../phase-2/index.md) — the deterministic trainer whose progress
  callback the CLI threads, and the persistence layer the CLI saves and loads through.
- [`docs/benchmarks.md`](../benchmarks.md) — baseline encode-latency and training-time
  measurements on the reference benchmark machine. Companion to the harness design doc.
- [`README.md`](../../README.md) — the user-facing installation, CLI examples, and
  benchmark summary table; the first-time reviewer's entry point.
- [`docs/bpetite-prd-v2.md`](../bpetite-prd-v2.md) — FR-30 through FR-37 (public API,
  CLI, quality gates, byte-typing); §Quality and Performance for the benchmark targets.
- [`src/bpetite/`](../../src/bpetite/) — Phase 4 source modules (`_cli.py`, `_ui.py`,
  `_banner.txt`).
- [`tests/test_cli.py`](../../tests/test_cli.py) — the subprocess-level contract test
  harness.
- [`scripts/`](../../scripts/) — Phase 4 operational scripts (`bench_encode.py`,
  `download_corpus.py`).
