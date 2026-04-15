<div align="center">

```
 _____                                                                                _____
( ___ )                                                                              ( ___ )
 |   |~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~|   |
 |   |  ███████████  ███████████  ██████████ ███████████ █████ ███████████ ██████████ |   |
 |   | ░░███░░░░░███░░███░░░░░███░░███░░░░░█░█░░░███░░░█░░███ ░█░░░███░░░█░░███░░░░░█ |   |
 |   |  ░███    ░███ ░███    ░███ ░███  █ ░ ░   ░███  ░  ░███ ░   ░███  ░  ░███  █ ░  |   |
 |   |  ░██████████  ░██████████  ░██████       ░███     ░███     ░███     ░██████    |   |
 |   |  ░███░░░░░███ ░███░░░░░░   ░███░░█       ░███     ░███     ░███     ░███░░█    |   |
 |   |  ░███    ░███ ░███         ░███ ░   █    ░███     ░███     ░███     ░███ ░   █ |   |
 |   |  ███████████  █████        ██████████    █████    █████    █████    ██████████ |   |
 |   | ░░░░░░░░░░░  ░░░░░        ░░░░░░░░░░    ░░░░░    ░░░░░    ░░░░░    ░░░░░░░░░░  |   |
 |___|~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~|___|
(_____)                                                                              (_____)
```

A deterministic byte-level BPE tokenizer in pure Python. Built from the algorithm up, as a careful reading of what GPT-2-style tokenization actually requires.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![Tests](https://github.com/dinesh-git17/bpetite/actions/workflows/tests.yml/badge.svg)](https://github.com/dinesh-git17/bpetite/actions/workflows/tests.yml)
[![Types](https://github.com/dinesh-git17/bpetite/actions/workflows/types.yml/badge.svg)](https://github.com/dinesh-git17/bpetite/actions/workflows/types.yml)
[![Stage](https://img.shields.io/badge/stage-v1-green)](#)

</div>

## What it is

`bpetite` trains a byte-level Byte Pair Encoding tokenizer, encodes UTF-8 text to token ids, decodes those ids back to the exact original bytes, and persists the whole thing to a single versioned JSON artifact.

The point of the project is the algorithm, not the scale. Every tie-break, every merge-application step, every loader validation, and every CLI channel boundary is load-bearing and has a test that fails loudly if it drifts. The implementation fits in roughly a thousand lines of typed Python with two runtime dependencies: `regex` for Unicode-aware pre-tokenization, and `rich` for the CLI presentation layer.

This is not a production tokenizer. See [Limits and non-goals](#limits-and-non-goals) for exactly what it does not try to do.

## Why this exists

Most BPE implementations ship either as black-box C extensions or as incidental parts of a much larger machine-learning stack. If you want to understand how byte-level BPE actually behaves on real Unicode text, both ends of that range leave you nowhere to read. `bpetite` is the middle: the trainer, encoder, decoder, and persistence layer written out plainly, with the mechanical invariants documented and exercised by a deterministic test suite.

The invariants the project takes most seriously, and pins down with named tests:

| Invariant                                                            | Enforced in                                       | Test                                                         |
| -------------------------------------------------------------------- | ------------------------------------------------- | ------------------------------------------------------------ |
| Tie-broken pairs select the lexicographically smaller id-pair        | `_trainer.py` pair-counting and selection loop    | `test_train_tie_breaking_selects_lexicographically_smallest` |
| Merges never cross a pre-tokenizer chunk boundary                    | Per-chunk pair enumeration in `_trainer.py`       | `test_trainer.py` negative-corpus chunk boundary test        |
| Saving the same tokenizer state twice produces byte-identical output | `sort_keys=True` and atomic `os.replace`          | `test_same_state_saved_twice_produces_identical_bytes`       |
| Decode is strict UTF-8, never replacement characters                 | `_decoder.py` uses `bytes.decode("utf-8")` strict | `test_decode_invalid_utf8_raises`                            |

## Get running in 60 seconds

### Prerequisites

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/), the only package manager this project uses
- macOS or Linux. Windows is not supported for v1.

### Install and test

```bash
git clone https://github.com/dinesh-git17/bpetite.git
cd bpetite
uv sync --locked
uv run pytest
```

`uv sync --locked` installs every dependency at the exact versions pinned in `uv.lock`. No surprise upgrades, no version drift between your machine and CI.

### Download the demo corpus

The provided helper fetches TinyShakespeare into `data/tinyshakespeare.txt`. The destination is `.gitignore`d, so re-running it is safe:

```bash
uv run python scripts/download_corpus.py
```

## Using the CLI

Three subcommands. Every machine-readable result is written to `stdout`. Banners, progress output, and errors go to `stderr`. You can pipe any of the three into downstream tooling without fear of interleaved human-readable noise.

### Train

Train a 512-token tokenizer on TinyShakespeare and write a Schema v1 JSON artifact:

```bash
uv run bpetite train \
  --input data/tinyshakespeare.txt \
  --vocab-size 512 \
  --output data/tinyshakespeare-512.json
```

`--vocab-size` is the mergeable vocabulary size. It must be at least 256, and the final artifact contains 256 base-byte tokens plus the merges the algorithm actually learns from the corpus. Pass `--force` to overwrite an existing output file.

The command ends by writing a one-line JSON summary on `stdout`:

```json
{
  "corpus_bytes": 1115394,
  "requested_vocab_size": 512,
  "actual_mergeable_vocab_size": 512,
  "special_token_count": 1,
  "elapsed_ms": 4620.24
}
```

### Encode

```bash
uv run bpetite encode \
  --model data/tinyshakespeare-512.json \
  --text "Hello, world!"
```

`stdout` receives a compact JSON array of token ids:

```json
[72, 408, 111, 44, 263, 270, 312, 33]
```

The exact ids depend on which merges the loaded model learned. A model trained with a larger `vocab_size` or on a different corpus will produce a different sequence for the same input text. Decoding the same sequence against the same model always reproduces the original bytes.

### Decode

`--ids` takes a space-separated list of token ids and writes the decoded text to `stdout` with no trailing newline:

```bash
uv run bpetite decode \
  --model data/tinyshakespeare-512.json \
  --ids 72 408 111 44 263 270 312 33
```

Output:

```
Hello, world!
```

If the concatenated bytes are not valid UTF-8, or if any id is not in the model's vocabulary, `decode` exits non-zero with a grep-friendly message on `stderr`.

## Testing

All four quality gates must pass before any commit:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict
```

The suite is deterministic. Re-running it produces the same merges, the same artifact bytes, and the same token ids every time.

## Benchmarks

Baseline measurements on an Apple M1 / 8 GB / macOS 26.3.1 / Python 3.12.12:

| Measurement                                                     | Value         |
| --------------------------------------------------------------- | ------------- |
| Training at `vocab_size=512` (full completion)                  | 4,620.24 ms   |
| Encode p50 over 100 runs of a 50-word sentence                  | 3.4399 ms     |
| Encode p99 over 100 runs of a 50-word sentence                  | 3.6521 ms     |
| Training at `vocab_size=32000` (early-stopped at 21,272 merges) | 184,923.74 ms |

These are single-machine, single-run snapshots, not a regression target. The full reproduction steps, scope notes on exactly what each timing measures, and the large-vocab early-stop explanation live in [`docs/benchmarks.md`](docs/benchmarks.md).

## Limits and non-goals

These are load-bearing. The project does not try to do any of them, and the README states them explicitly so nobody has to open the PRD to find out.

- **Not a production tokenizer.** `bpetite` is educational and local-only. It is not a tokenizer service, not optimized for large corpora, and not a replacement for any shipping NLP stack.
- **No exact GPT-2 or `tiktoken` parity guarantee.** `bpetite` is byte-level BPE trained from scratch on whatever corpus you hand it. Its merges and token ids are determined by its own algorithm against its own pre-tokenizer regex. Token ids will not match `tiktoken`, and no claim of compatibility is made or tested.
- **No WordPiece, Unigram, or SentencePiece.** v1 implements byte-level BPE and nothing else.
- **No web app, REST API, hosted service, or mobile client.** The only runtime surfaces are the Python library and the local CLI.
- **No PyPI publication in v1.** Install by cloning the repo. Nothing is published to any package index.
- **macOS and Linux only.** Windows is not a supported execution target for v1.

The authoritative source for these is the `Non-Goals` and `Constraints` sections of `docs/bpetite-prd-v2.md`.

## Repository layout

```
src/bpetite/        package source, public API via Tokenizer
  _trainer.py       deterministic BPE trainer
  _encoder.py       greedy merge-rank encoder
  _decoder.py       byte-level decoder with strict UTF-8
  _persistence.py   Schema v1 atomic save and full loader validation
  _cli.py           argparse plus the Rich presentation layer
tests/              pytest suite, importlib mode, no tests/__init__.py
docs/               PRD, task list, phase-2 narrative docs, benchmarks
scripts/            download_corpus.py, bench_encode.py, repo hooks
```
