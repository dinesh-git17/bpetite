#!/usr/bin/env python3
"""Encode-path benchmark harness for bpetite.

Loads a saved tokenizer artifact, encodes a fixed 50-word sentence a
configurable number of times (default ``100`` per the PRD), and reports
per-run elapsed wall time in milliseconds with two summary statistics:

* ``p50`` — the statistical median of the sample (``statistics.median``).
* ``p99`` — the nearest-rank percentile on the sorted sample.

The nearest-rank definition is the one the PRD pins: sort the samples
ascending, take the ``ceil(p/100 * N)``\\ th element (1-indexed). For
``p=99`` and ``N=100``, that is index ``99`` one-based, which is
``sorted_samples[98]`` zero-based. This differs from linear interpolation
(which ``numpy.percentile`` uses by default) and is the only variant the
PRD and task list reference.

Output channels follow the rest of the bpetite CLI contract: a compact
JSON summary goes to ``stdout`` so downstream tooling can scrape it, and
human-readable status lines go to ``stderr`` so a terminal reviewer can
read them without parsing JSON. Nothing on stdout except the summary.

The script is standalone by design. It imports the installed ``bpetite``
package via ``from bpetite import Tokenizer``, so it exercises the same
``load`` and ``encode`` paths a user would hit from the CLI. It does not
touch the ``_cli`` module, does not drive a subprocess, and does not
depend on ``rich`` — the rendering layer is plain ``sys.stderr.write``
to keep the script simple and portable across terminals.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time

from bpetite import Tokenizer

_BENCHMARK_SENTENCE = (
    "The quick brown fox jumps over the lazy dog beside twelve ancient "
    "scrolls while the wizard carefully studies glowing library shelves "
    "filled with crumbling leather-bound volumes and parchment lore that "
    "crackles gently with age as the silver moon rises slowly above "
    "distant mountain peaks casting long shadows across silent fields"
)
_DEFAULT_RUNS = 100
_SENTENCE_WORD_COUNT = 50


def main() -> int:
    """Run the encode benchmark and print a JSON summary.

    Returns:
        ``0`` on a successful benchmark run, ``1`` if the model cannot be
        loaded or if the configured sentence is no longer 50 words long
        (a defensive check against accidental edits to the constant).
    """
    args = _parse_args()

    if len(_BENCHMARK_SENTENCE.split()) != _SENTENCE_WORD_COUNT:
        sys.stderr.write(
            "Error: _BENCHMARK_SENTENCE is no longer "
            f"{_SENTENCE_WORD_COUNT} words. Restore it before benchmarking.\n"
        )
        return 1

    try:
        tokenizer = Tokenizer.load(args.model)
    except FileNotFoundError:
        sys.stderr.write(f"Error: model not found: {args.model}\n")
        return 1
    except OSError as exc:
        sys.stderr.write(f"Error: model unreadable: {args.model}: {exc}\n")
        return 1
    except (KeyError, ValueError) as exc:
        sys.stderr.write(f"Error: could not load {args.model}: {exc}\n")
        return 1

    samples_ms = _run_encode_samples(tokenizer, _BENCHMARK_SENTENCE, args.runs)

    p50_ms = statistics.median(samples_ms)
    p99_ms = _nearest_rank(samples_ms, percentile=99)
    mean_ms = statistics.fmean(samples_ms)
    min_ms = min(samples_ms)
    max_ms = max(samples_ms)

    _render_human_summary(
        model_path=args.model,
        runs=args.runs,
        token_count=len(tokenizer.encode(_BENCHMARK_SENTENCE)),
        p50_ms=p50_ms,
        p99_ms=p99_ms,
        mean_ms=mean_ms,
        min_ms=min_ms,
        max_ms=max_ms,
    )

    summary = {
        "model": args.model,
        "runs": args.runs,
        "sentence_word_count": _SENTENCE_WORD_COUNT,
        "p50_ms": round(p50_ms, 4),
        "p99_ms": round(p99_ms, 4),
        "mean_ms": round(mean_ms, 4),
        "min_ms": round(min_ms, 4),
        "max_ms": round(max_ms, 4),
    }
    sys.stdout.write(json.dumps(summary) + "\n")
    sys.stdout.flush()
    return 0


def _positive_int(value: str) -> int:
    """Argparse type that accepts strictly positive integers.

    The nearest-rank percentile and median summary steps both require at
    least one sample; zero or negative ``--runs`` values would otherwise
    raise ``StatisticsError`` deep inside ``main`` and print a Python
    traceback instead of a clean usage error. Rejecting the value here
    routes the failure through argparse, which emits a standard exit
    code 2 and its own error message.
    """
    try:
        parsed = int(value)
    except ValueError as exc:
        message = f"--runs must be an integer, got {value!r}"
        raise argparse.ArgumentTypeError(message) from exc
    if parsed < 1:
        message = f"--runs must be >= 1, got {parsed}"
        raise argparse.ArgumentTypeError(message)
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bench_encode",
        description=(
            "Encode a fixed 50-word sentence N times against a saved "
            "bpetite tokenizer and report p50 (median) and p99 "
            "(nearest-rank) encode latency in milliseconds."
        ),
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Path to a Schema v1 bpetite tokenizer artifact.",
    )
    parser.add_argument(
        "--runs",
        type=_positive_int,
        default=_DEFAULT_RUNS,
        help=f"Number of encode runs to sample (default: {_DEFAULT_RUNS}).",
    )
    return parser.parse_args()


def _run_encode_samples(tokenizer: Tokenizer, sentence: str, runs: int) -> list[float]:
    """Encode ``sentence`` ``runs`` times and return per-run wall times.

    Each sample is the wall-clock duration of a single ``encode`` call in
    milliseconds, captured with ``time.perf_counter()``. The return value
    preserves insertion order so callers that want to inspect drift over
    the run can do so; callers that want sorted samples should sort the
    copy themselves.
    """
    samples_ms: list[float] = []
    encode = tokenizer.encode
    for _ in range(runs):
        t0 = time.perf_counter()
        encode(sentence)
        t1 = time.perf_counter()
        samples_ms.append((t1 - t0) * 1000.0)
    return samples_ms


def _nearest_rank(samples_ms: list[float], *, percentile: int) -> float:
    """Return the nearest-rank percentile of ``samples_ms``.

    Sorts the samples ascending and returns the element at index
    ``ceil(p/100 * N) - 1`` (zero-indexed). This matches the PRD's
    "nearest-rank on the sorted samples" phrasing and is intentionally
    distinct from linear-interpolation percentile methods used by
    ``numpy.percentile`` and ``statistics.quantiles`` — both give
    subtly different values for small ``N``.
    """
    if not samples_ms:
        sentinel = "nearest-rank percentile of an empty sample is undefined"
        raise ValueError(sentinel)
    ordered = sorted(samples_ms)
    rank = math.ceil(percentile / 100 * len(ordered))
    return ordered[rank - 1]


def _render_human_summary(
    *,
    model_path: str,
    runs: int,
    token_count: int,
    p50_ms: float,
    p99_ms: float,
    mean_ms: float,
    min_ms: float,
    max_ms: float,
) -> None:
    lines = [
        "",
        "bpetite encode benchmark",
        f"  model:          {model_path}",
        f"  runs:           {runs}",
        f"  sentence words: {_SENTENCE_WORD_COUNT}",
        f"  encoded tokens: {token_count}",
        "",
        f"  p50 (median):   {p50_ms:.4f} ms",
        f"  p99 (nearest):  {p99_ms:.4f} ms",
        f"  mean:           {mean_ms:.4f} ms",
        f"  min:            {min_ms:.4f} ms",
        f"  max:            {max_ms:.4f} ms",
        "",
    ]
    sys.stderr.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
