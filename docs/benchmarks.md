---
title: Benchmarks
description: Baseline training and encode-latency measurements for the bpetite v1 release, captured on the reference benchmark machine.
slug: benchmarks
order: 2
category: Reference
published: true
---

# bpetite benchmarks

This document records the benchmark evidence the PRD requires for the
`bpetite` v1 release: one small-vocab training run on TinyShakespeare, one
encode-latency measurement over 100 runs of a fixed 50-word sentence, and
one large-vocab completion check. The numbers below are captured manually
on the benchmark machine and are not re-run in CI. The harness scripts are
deterministic, so re-running them on the same machine will produce matching
orders of magnitude even though individual timings vary run to run.

All commands assume the repository root as the working directory and a
fresh `uv sync --locked` before starting.

## Environment

- **Machine:** Apple M1, 8 GB RAM
- **OS:** macOS 26.3.1 (Darwin 25.3.0)
- **Python:** 3.12.12 (uv-managed venv)
- **bpetite commit:** `ce2dea1` (runtime under test; this Task 4-4 PR adds the benchmark harness on top without touching runtime code)

To reproduce the environment report:

```bash
uv run python --version
uname -a
```

## Preparation

Download the TinyShakespeare demo corpus. The destination is `.gitignore`d,
so this is safe to run repeatedly:

```bash
uv run python scripts/download_corpus.py
```

Expected stderr tail after a successful fetch:

```
Saved 1,115,394 bytes to data/tinyshakespeare.txt
```

## Training at `vocab_size=512`

The PRD fixes `vocab_size=512` as the small-vocab training benchmark. Train
directly through the CLI so the recorded number reflects the deterministic
BPE trainer running against a real UTF-8 corpus through the real artifact
path.

```bash
uv run bpetite train \
  --input data/tinyshakespeare.txt \
  --vocab-size 512 \
  --output data/tinyshakespeare-512.json \
  --force
```

The `train` CLI subcommand emits a JSON summary on stdout that contains
the `elapsed_ms` field to record below. **Scope of `elapsed_ms`:** the
timer in `_cmd_train` starts immediately after the UTF-8 corpus read
(`_cli.py:112`) and stops immediately before the atomic artifact save
(`_cli.py:114`). It therefore measures the trainer span only:
pre-tokenization plus the merge loop. It does **not** include file I/O
on either end, argparse/import/banner rendering, or Python startup. That
is the right scope for evaluating the BPE algorithm in isolation, but it
is not the command's wall-clock total. The stderr progress panel is
informational only.

- **`vocab_size=512` trainer elapsed time:** **4,620.24 ms** (≈ 4.62 s). Full completion with no early stop. Trainer span only, per the `elapsed_ms` scope note above.
- **Actual mergeable vocab size:** 512 (256 base bytes + 256 merges; matches the request exactly).
- **Corpus bytes:** 1,115,394 (sanity-matches the Step 1 download size).

## Encode latency: 50-word sentence over 100 runs

Once `data/tinyshakespeare-512.json` exists, run the encode benchmark
against it. The script encodes a fixed 50-word sentence 100 times, reports
`p50` via the statistical median and `p99` via nearest-rank on the sorted
samples, and emits a one-line JSON summary on stdout.

```bash
uv run python scripts/bench_encode.py \
  --model data/tinyshakespeare-512.json
```

Expected stderr shape:

```
bpetite encode benchmark
  model:          data/tinyshakespeare-512.json
  runs:           100
  sentence words: 50
  encoded tokens: <N>

  p50 (median):   <ms> ms
  p99 (nearest):  <ms> ms
  mean:           <ms> ms
  min:            <ms> ms
  max:            <ms> ms
```

Record the two task-list-required percentiles below. The other summary
statistics are informational and are not gated by the task list, but they
give useful context on run-to-run variance.

- **Encoded tokens:** 171 (≈ 3.42 tokens per English word for the 50-word benchmark sentence, typical for a 512-vocab tokenizer that only has budget to capture short bigrams).
- **p50 (median):** **3.4399 ms**
- **p99 (nearest-rank):** **3.6521 ms**
- **Mean:** 3.4512 ms
- **Min / Max:** 3.3617 ms / 3.6998 ms (≈ 10 % spread around the median; no long tail, no GC outliers).

## Demo training at `vocab_size=32000`

The large-vocab completion check is demo-only and is not gated by CI. The
goal is to prove the deterministic BPE trainer terminates cleanly and
writes a schema v1 artifact at the production-scale vocab target. Run the
same CLI path as the 512-vocab run, just with a larger target.

```bash
time uv run bpetite train \
  --input data/tinyshakespeare.txt \
  --vocab-size 32000 \
  --output data/tinyshakespeare-32000.json \
  --force
```

Two distinct timings come out of this command:

1. **Trainer elapsed:** the CLI's `elapsed_ms` JSON field, measuring the
   same trainer span described in the 512 section (pre-tokenization +
   merge loop only, no file I/O, no Python startup).
2. **Command wall clock:** the outer `time` total, measuring everything
   the shell waited on: Python process startup, import, argparse, banner
   render, corpus read, the `elapsed_ms` trainer span itself, atomic
   save, and the completion panel render.

Both are recorded below. The two numbers differ by the non-trainer
overhead of a full `train` invocation. At the 32000 scale that delta is
effectively rounding error (~0.2 s out of 185 s total), but at smaller
scales it would dominate and the two measurements would tell different
stories. For the 512 section above, only `elapsed_ms` is recorded
because the outer `time` was not captured at that step; the two are
**not interchangeable** and should not be compared across sections as
if they were the same measurement.

- **`vocab_size=32000` completion status:** **early-stopped at 21272 merges** of 31744 planned. TinyShakespeare is only ~1.1 MB and ran out of distinct byte-pair co-occurrences well before the 32000 target. This is the documented early-stop path in `_trainer.py` (`if not pair_counts: break`) and is not a failure. It is the deterministic trainer correctly refusing to invent merges from nothing.
- **`vocab_size=32000` trainer elapsed time (`elapsed_ms`):** **184,923.74 ms** (≈ 3 min 4.9 s). Trainer span only.
- **`vocab_size=32000` command wall clock (outer `time`):** **3:05.09** (= 185.09 s), with `184.02 s user`, `0.89 s sys`, and `99% cpu`. Single-threaded pure Python on one core, with no thrashing. The ~170 ms gap above `elapsed_ms` is corpus read + argparse + import + banner render + atomic save + Python startup combined.
- **Actual mergeable vocab size:** **21,528** (256 base bytes + 21272 merged tokens).

## Notes

- The benchmark sentence is hard-coded in `scripts/bench_encode.py` as
  `_BENCHMARK_SENTENCE`. It was chosen to hit 50 words after whitespace
  split and to mix common English stopwords with less-common words so the
  encode path exercises both high-frequency merged tokens and lower-
  frequency fallback bytes. Do not edit the constant between runs. The
  script asserts the 50-word count on startup and aborts otherwise.
- All timings are single-machine, single-run snapshots. They are not
  CI-gated and are not a regression target. Their purpose is to establish
  a baseline for the v1 release and to document that the deterministic
  pure-Python path is usable at both the small and large vocab targets
  the PRD mentions.
