---
title: Benchmark Harness
description: Encode-latency harness design, nearest-rank percentile math, defensive sentence-length check, and the elapsed_ms trainer span versus command wall clock distinction.
slug: phase-4-benchmark-harness
order: 33
category: Phase 4
published: true
---

# Benchmark Harness: encode-latency measurement design

## TL;DR

- The encode benchmark harness encodes a fixed 50-word sentence 100 times against a
  saved Schema v1 tokenizer artifact, reports `p50` via `statistics.median` and `p99`
  via nearest-rank on the sorted sample, and emits a compact JSON summary on stdout
  alongside a readable text panel on stderr.
- The nearest-rank percentile is `sorted_samples[ceil(p/100 * N) - 1]`. For p99 with
  N=100, that is `sorted_samples[98]` zero-indexed. This is intentionally distinct from
  `numpy.percentile` and `statistics.quantiles`, both of which use linear interpolation
  by default and produce subtly different values for small N.
- `elapsed_ms` from the `train` CLI summary wraps only `_train_with_progress` at
  `_cli.py:112-114`. It is the **trainer span**, not the **command wall clock**. The
  two measurements differ by file I/O, argparse, imports, banner render, atomic save,
  and Python startup. They are not interchangeable and must never be presented as if
  they were.

## What lives here

| File                         | Purpose                                                                                                                                                                                                                  |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `scripts/bench_encode.py`    | Standalone encode-latency benchmark harness; imports only `from bpetite import Tokenizer`; writes JSON to stdout and a panel to stderr via plain `sys.stderr.write` (no Rich dependency)                                 |
| `scripts/download_corpus.py` | TinyShakespeare fetcher into `data/tinyshakespeare.txt`; reference for any benchmark reproduction. Ignored by `.gitignore`; the only network-touching code in the repo                                                   |
| `src/bpetite/_cli.py`        | Owns the `elapsed_ms` field in the `train` JSON summary; `_cmd_train` starts the timer at `_cli.py:112` and stops it at `_cli.py:114`, wrapping only `_train_with_progress`                                              |
| `docs/benchmarks.md`         | Baseline measurements companion: machine fingerprint, captured numbers, reproduction commands. The harness design (this doc) is separate from the results page so the methodology and the values can drift independently |

## Key invariants

| FR / Area                    | Invariant                                                                                                                                                                         | Consequence if violated                                                                                                                                                                           |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR-30                        | The harness imports only the public `from bpetite import Tokenizer`. It does not touch `_cli`, `_encoder`, or any other internal module.                                          | Drift from the public API surface; future Phase 5 reference comparison work that wants to add `compare-tiktoken` would need to refactor the harness instead of extending it.                      |
| (local)                      | `_BENCHMARK_SENTENCE` is exactly 50 words after `str.split()`. A defensive guard at startup aborts the run with exit 1 if the constant has been edited to a different word count. | A silent edit from 50 to 49 or 51 words invalidates every historical comparison against the published p50 and p99 values.                                                                         |
| (local)                      | Percentile math is nearest-rank, not linear-interpolation. `_nearest_rank` returns `sorted[ceil(p/100 * N) - 1]`, and the docstring explicitly contrasts this with numpy.         | Replacing `_nearest_rank` with `numpy.percentile(samples, 99)` would shift the reported p99 value by a small but non-zero amount, breaking byte-equality assertions against the published values. |
| (local)                      | `elapsed_ms` in any document or test that surfaces it is labeled with its true scope (trainer span only, excludes file I/O and Python startup).                                   | A reader comparing `elapsed_ms` against outer `time(1)` total interprets the gap as algorithmic overhead rather than process startup, drawing wrong conclusions about the trainer.                |
| PRD §Quality and Performance | TinyShakespeare at `vocab_size=512` completes in `<= 60s` on the documented benchmark machine; encode `p99 < 100ms` over 100 runs of a 50-word sentence on the same machine.      | The release evidence in `docs/benchmarks.md` would no longer satisfy the PRD performance targets; v1 release gate would fail.                                                                     |

## Walkthrough

### The harness pipeline

```
argparse (--model, --runs)
 |
 v
defensive check: len(_BENCHMARK_SENTENCE.split()) == 50  -> exit 1 if not
 |
 v
Tokenizer.load(args.model)
   except FileNotFoundError -> exit 1
   except OSError           -> exit 1
   except (KeyError, ValueError) -> exit 1
 |
 v
samples_ms = _run_encode_samples(tokenizer, _BENCHMARK_SENTENCE, runs)
   for _ in range(runs):
       t0 = perf_counter()
       tokenizer.encode(sentence)
       t1 = perf_counter()
       samples_ms.append((t1 - t0) * 1000.0)
 |
 v
p50 = statistics.median(samples_ms)
p99 = _nearest_rank(samples_ms, percentile=99)
mean = statistics.fmean(samples_ms)
min, max = min(samples_ms), max(samples_ms)
 |
 v
_render_human_summary(...)  -> stderr (plain sys.stderr.write, no Rich)
sys.stdout.write(json.dumps(summary) + "\n")  -> stdout (compact JSON)
```

The harness is intentionally minimal. It does not wrap the encode call in a context
manager, does not warm up the JIT (Python has none), and does not exclude an outlier
window. Single sample, accumulated across `runs`, sorted at the end, percentiles
computed on the raw distribution.

### The 50-word benchmark sentence

`_BENCHMARK_SENTENCE` is hardcoded in `scripts/bench_encode.py`:

```python
_BENCHMARK_SENTENCE = (
    "The quick brown fox jumps over the lazy dog beside twelve ancient "
    "scrolls while the wizard carefully studies glowing library shelves "
    "filled with crumbling leather-bound volumes and parchment lore that "
    "crackles gently with age as the silver moon rises slowly above "
    "distant mountain peaks casting long shadows across silent fields"
)
_DEFAULT_RUNS = 100
_SENTENCE_WORD_COUNT = 50
```

The sentence mixes common English stopwords (`the`, `a`, `with`, `as`) with
less-common words (`crumbling`, `parchment`, `crackles`, `mountain`) so the encode
path exercises both high-frequency merged tokens and lower-frequency fallback bytes.
A pure stopword sentence would land entirely in merged tokens for any reasonable
training corpus, masking the latency cost of unmerged byte sequences. A pure
out-of-distribution sentence would fall back to bytes too often, masking the cost of
the merge-application loop. The mix is the point.

### The defensive 50-word guard

The constant is checked at startup before any other work happens:

```python
# scripts/bench_encode.py main()

if len(_BENCHMARK_SENTENCE.split()) != _SENTENCE_WORD_COUNT:
    sys.stderr.write(
        "Error: _BENCHMARK_SENTENCE is no longer "
        f"{_SENTENCE_WORD_COUNT} words. Restore it before benchmarking.\n"
    )
    return 1
```

The guard exists because an editor can silently change the word count by adjusting any
single word into a multi-word phrase, or by accidentally removing a space. A reader
running the benchmark against a 49-word or 51-word sentence and comparing the resulting
p50 and p99 against the values in `docs/benchmarks.md` would conclude that the encoder
had drifted, when in fact the input had drifted. The guard catches this on startup,
before the first encode call, and returns 1 with a clear message on stderr. There is
no recovery path: the constant must be restored to exactly 50 words before the
harness will run.

### Per-run timing with `time.perf_counter`

Each sample is the wall-clock duration of a single `encode` call in milliseconds:

```python
# scripts/bench_encode.py _run_encode_samples()

def _run_encode_samples(tokenizer: Tokenizer, sentence: str, runs: int) -> list[float]:
    samples_ms: list[float] = []
    encode = tokenizer.encode
    for _ in range(runs):
        t0 = time.perf_counter()
        encode(sentence)
        t1 = time.perf_counter()
        samples_ms.append((t1 - t0) * 1000.0)
    return samples_ms
```

Two small details matter. **`encode = tokenizer.encode`** binds the bound method to a
local once before the loop, avoiding 100 attribute lookups during timing. The cost is
a fraction of a microsecond per lookup, negligible in absolute terms, but the local
binding makes the timed code path as direct as possible. **`time.perf_counter()`** is
the highest-resolution monotonic clock the standard library exposes and is the right
choice for short-interval wall-clock measurement; it is unaffected by system clock
adjustments mid-run.

The return value preserves insertion order. Callers that want sorted samples (the
percentile functions in `main`) sort their own copy. The unsorted samples are also
exposed indirectly through the min/max statistics in the JSON summary, which can hint
at variance even though the harness does not report a standard deviation.

### Nearest-rank percentile

The percentile function is the most subtle piece of the harness:

```python
# scripts/bench_encode.py _nearest_rank()

def _nearest_rank(samples_ms: list[float], *, percentile: int) -> float:
    if not samples_ms:
        sentinel = "nearest-rank percentile of an empty sample is undefined"
        raise ValueError(sentinel)
    ordered = sorted(samples_ms)
    rank = math.ceil(percentile / 100 * len(ordered))
    return ordered[rank - 1]
```

The math: sort the samples ascending, compute `rank = ceil(p/100 * N)` (1-indexed), and
return the element at position `rank - 1` (zero-indexed). For `p=99` and `N=100`, that
is `rank = ceil(99) = 99` → index `98` → the element at position 98 in the sorted
list, which for a 100-element sample is the second-largest value.

The PRD pins this exact variant. There are several percentile conventions in common
use, and they produce different values for the same sample:

- **Nearest-rank (this harness):** `sorted[ceil(p/100 * N) - 1]`. Always returns an
  element that is actually present in the sample. For p99 of `[1, 2, ..., 100]`,
  returns `99`.
- **Linear interpolation (`numpy.percentile` default, `statistics.quantiles`):**
  computes a position `(p/100) * (N - 1)` and linearly interpolates between the two
  surrounding samples. Can return a value not actually present in the sample. For p99
  of `[1, 2, ..., 100]`, returns approximately `99.01`.
- **Lower / higher / midpoint variants:** rounds the position to the nearest lower,
  higher, or midpoint integer respectively.

For small `N`, the difference between nearest-rank and linear interpolation is small
in absolute terms but visible in the documented values. The published baselines in
`docs/benchmarks.md` were computed with this `_nearest_rank` function. Replacing it
with `numpy.percentile(samples, 99)` would shift the reported p99 by a fraction of a
millisecond, which is enough to break a byte-equality assertion against the published
value.

### `--runs` validation through a custom argparse type

The harness accepts `--runs N` to override the default of 100. Without input
validation, `--runs 0` or `--runs -1` would let the loop body run zero times,
producing an empty `samples_ms` list, and then crash inside `statistics.median` with a
`StatisticsError`. The Python traceback would dump to stderr at the very end of an
otherwise-successful argparse and load step. That is a poor failure mode.

The harness routes the failure through argparse instead, with a custom type:

```python
# scripts/bench_encode.py

def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        message = f"--runs must be an integer, got {value!r}"
        raise argparse.ArgumentTypeError(message) from exc
    if parsed < 1:
        message = f"--runs must be >= 1, got {parsed}"
        raise argparse.ArgumentTypeError(message)
    return parsed
```

Argparse calls `_positive_int` for every `--runs` value before the main body runs.
`ArgumentTypeError` is the standard way to reject a value: argparse catches it,
formats a usage message, prints to stderr, and exits with code 2 (its default for
usage errors). No traceback, no internal `StatisticsError`, just a clean rejection at
the argument boundary.

### The `elapsed_ms` scope distinction

The most important point in this doc is that `elapsed_ms` from the `train` CLI is
not the command wall clock.

The `train` subcommand starts a `time.perf_counter` immediately after the corpus read
and stops it immediately before the artifact save:

```python
# src/bpetite/_cli.py _cmd_train (excerpt around lines 109-121)

corpus = _read_corpus_or_exit(args.input)
corpus_bytes = len(corpus.encode("utf-8"))

t0 = time.perf_counter()
result = _train_with_progress(corpus, args.vocab_size)
elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

tokenizer = Tokenizer(...)
_save_or_exit(tokenizer, args.output, overwrite=bool(args.force))
```

The timer at line 112 starts **after** `_read_corpus_or_exit`, so file reading is
excluded. The timer at line 114 stops **before** `_save_or_exit`, so the atomic save
is excluded. Argparse, the import of `bpetite._cli`, the banner render, the
configuration panel render, the completion panel render, and Python startup all sit
outside the timer entirely.

The two measurements that emerge from a single `train` invocation are therefore
distinct:

| Measurement                  | What is timed                                                                                                                               | What is excluded                                                                                                                   |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `elapsed_ms` (trainer span)  | `_train_with_progress(corpus, vocab_size)`: pre-tokenization + the merge loop + every `ProgressEvent` callback                              | File read, UTF-8 decode, argparse, Python startup, banner render, configuration panel render, atomic save, completion panel render |
| Outer `time(1)` (wall clock) | The full command from the shell's perspective: Python startup, all imports, argparse, banner, panels, file I/O, training, atomic save, exit | Nothing the shell invocation does                                                                                                  |

At `vocab_size=32000` on TinyShakespeare, the trainer span is 184,923.74 ms and the
outer `time(1)` total is 185.09 s (185,090 ms). The delta is 166.26 ms, dominated by
Python startup and atomic save. As a fraction of the total it is rounding error.

At `vocab_size=512` on the same corpus, the trainer span is 4,620.24 ms. The outer
`time(1)` total at the same scale is also captured in `docs/benchmarks.md`, and even
at this scale the gap is meaningful relative to the trainer span. At `vocab_size=256`
(zero merges, instant trainer span) the trainer span would be a fraction of a
millisecond and the outer `time(1)` would still be hundreds of milliseconds dominated
entirely by process startup.

This is why the two measurements **must never be presented as interchangeable**. A
reader cross-comparing a `vocab_size=512` `elapsed_ms` against a `vocab_size=32000`
outer `time(1)` would draw wildly wrong conclusions about how the trainer scales.
`docs/benchmarks.md` records both measurements explicitly with named scope notes for
each, and the README references the same numbers with the same explicit framing.

### Output channels

The harness follows the same channel discipline as the CLI proper, but implements it
without any Rich dependency. The script is standalone and meant to be portable across
machines and Python environments where `rich` may or may not be installed.

**stdout (machine-readable):** A compact JSON summary, one line, ending with a
newline:

```json
{
  "model": "data/tinyshakespeare-512.json",
  "runs": 100,
  "sentence_word_count": 50,
  "p50_ms": 3.4399,
  "p99_ms": 3.6521,
  "mean_ms": 3.4512,
  "min_ms": 3.3617,
  "max_ms": 3.6998
}
```

Eight keys, all numeric except the model path. Rounded to four decimal places to keep
the JSON readable while preserving sub-microsecond precision.

**stderr (human-readable):** A rendered text block written via plain `sys.stderr.write`:

```
bpetite encode benchmark
  model:          data/tinyshakespeare-512.json
  runs:           100
  sentence words: 50
  encoded tokens: 171

  p50 (median):   3.4399 ms
  p99 (nearest):  3.6521 ms
  mean:           3.4512 ms
  min:            3.3617 ms
  max:            3.6998 ms
```

The harness intentionally does not import `rich` or `_ui.py` for the stderr render.
The CLI proper uses Rich because the configuration and completion panels are part of
the user-facing CLI experience. The benchmark harness is not a user-facing CLI; it is
an operational script. Plain `sys.stderr.write` of pre-formatted lines is simpler,
more portable, and produces output that is byte-stable across terminal widths and
Rich versions.

## Failure modes

| Failure                                                             | Exception type / exit code | Caught by                                                                   |
| ------------------------------------------------------------------- | -------------------------- | --------------------------------------------------------------------------- |
| `--runs 0` or any non-positive integer                              | exit 2 (argparse)          | `_positive_int` argparse type at `bench_encode.py:116-134`                  |
| `--runs` value that does not parse as an integer                    | exit 2 (argparse)          | `_positive_int` argparse type at `bench_encode.py:116-134`                  |
| Model artifact does not exist                                       | exit 1                     | `except FileNotFoundError` in `main` at `bench_encode.py:72-74`             |
| Model artifact unreadable (permission denied, is a directory)       | exit 1                     | `except OSError as exc` in `main` at `bench_encode.py:75-77`                |
| Model artifact corrupt or schema-invalid                            | exit 1                     | `except (KeyError, ValueError) as exc` in `main` at `bench_encode.py:78-80` |
| `_BENCHMARK_SENTENCE` accidentally edited to not exactly 50 words   | exit 1                     | Defensive startup guard in `main` at `bench_encode.py:63-68`                |
| Empty sample list reaches `_nearest_rank` (impossible via `--runs`) | `ValueError`               | Sentinel raise in `_nearest_rank` at `bench_encode.py:189-191`              |

### Silent failure modes called out by name

**`elapsed_ms` mislabeled as wall clock.** The hardest failure to notice in
documentation is conflating `elapsed_ms` with the outer `time(1)` total. The number
in the JSON summary is real, the value is correct, but the surrounding label drifts
to something like "the full pipeline including corpus read and atomic save". A
reviewer cross-referencing the field against a `time bpetite train` invocation sees
a delta and concludes the trainer is slower than the JSON claims, when the trainer
is exactly as fast as the JSON claims and the outer wall clock is just measuring
something different. Every label on this field, in `docs/benchmarks.md`, in the
README, and in this doc, must explicitly name the scope as "trainer span only,
excludes file I/O, argparse, Python startup".

**Percentile drift from numpy.** A maintainer reaching for a more "standard" library
might replace `_nearest_rank` with `numpy.percentile(samples, 99)`. The two functions
agree on large samples and disagree on small ones. The harness runs N=100 by default,
which is squarely in the regime where the disagreement is visible. A drop-in
replacement would silently shift every published p99 value by a small amount, and
historical comparisons against `docs/benchmarks.md` would all need to be re-baselined.
The `_nearest_rank` docstring documents this contrast explicitly to discourage the
substitution.

**Sentence-length silent edit.** A typo or auto-correction that turns one word into
two ("twelve ancient" → "twelvescrolls"... or its inverse) silently invalidates every
historical p50 and p99 comparison. The startup guard is the only defense, and it only
fires if the resulting word count differs from 50. An edit that preserves the word
count but changes the content (replacing one word with another) would not be caught
by the guard, but it would invalidate cross-machine comparison just as severely. The
sentence is therefore considered append-only: do not edit existing words, do not add
words, do not remove words.

## Related reading

- [CLI Contract](cli-contract.md): the `train` subcommand's `elapsed_ms` field, the
  channel discipline the harness mirrors without Rich, and the `_cmd_train` timer
  boundary at `_cli.py:112-114`.
- [Rich Presentation Layer](rich-presentation.md): why the CLI proper uses Rich for
  panels and the harness deliberately does not.
- [`docs/benchmarks.md`](../benchmarks.md): baseline values produced by this
  harness; reference machine fingerprint; full reproduction commands.
- [`README.md`](../../README.md): user-facing benchmark summary table; cross-links
  to `docs/benchmarks.md` for full reproduction details.
- [`docs/bpetite-prd-v2.md`](../bpetite-prd-v2.md): §Quality and Performance
  performance targets; FR-30 (public API surface the harness uses).
- [`scripts/bench_encode.py`](../../scripts/bench_encode.py): full harness source.
- [`src/bpetite/_cli.py`](../../src/bpetite/_cli.py): `_cmd_train` and the
  `elapsed_ms` timer boundaries.
