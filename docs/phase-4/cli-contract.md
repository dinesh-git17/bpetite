---
title: CLI Contract
description: Channel discipline, exit codes, JSON output shapes, argparse patterns, and progress-callback wiring for the bpetite CLI.
slug: phase-4-cli-contract
order: 31
category: Phase 4
published: true
---

# CLI Contract: stdout/stderr channel discipline, exit codes, JSON output shapes

## TL;DR

- Every machine-readable result (`train` JSON summary, `encode` compact JSON array,
  `decode` raw text) is written via `sys.stdout.write` with no Rich involvement. Every
  banner, panel, progress line, and error panel is rendered through a shared Rich
  `Console` constructed with `stderr=True`. A single stray `print()` call on the wrong
  channel fails the contract test suite immediately.
- The `train` progress callback is threaded through internal `train_bpe`, not through
  public `Tokenizer.train`. FR-30 pins the public method signature to
  `(corpus, vocab_size)` exactly, so the CLI calls `train_bpe` directly with a callback
  closure and wraps the returned `TrainerResult` in a `Tokenizer` via the existing
  constructor.
- Subprocess-level tests in `tests/test_cli.py` drive the installed console entry point
  through `Path(sys.executable).parent / "bpetite"` rather than a second `uv run` layer,
  preserving strict stdout/stderr separation and avoiding nested venv resolution.

## What lives here

| File                      | Purpose                                                                                                                                                                                     |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/bpetite/_cli.py`     | `main`, `_build_parser`, the three subcommand handlers (`_cmd_train`, `_cmd_encode`, `_cmd_decode`), the `_train_with_progress` callback wiring, every error router, every stdout write     |
| `src/bpetite/_trainer.py` | `train_bpe(corpus, vocab_size, *, progress)` and the `ProgressEvent` dataclass the CLI imports; the internal entry point the CLI uses for the callback-enabled training path                |
| `src/bpetite/_ui.py`      | The shared stderr `Console` and the panel helpers the handlers render through (documented in full at [Rich Presentation Layer](rich-presentation.md))                                       |
| `tests/test_cli.py`       | 13 subprocess-level contract tests covering every happy path, every runtime failure mode, and strict channel separation; two session-scoped fixtures (trained artifact and progress corpus) |
| `tests/conftest.py`       | `tiny_corpus_path` session fixture shared with the CLI tests; returns the filesystem path to `tests/fixtures/tiny.txt`                                                                      |

## Key invariants

| FR      | Invariant                                                                                                                                                                    | Consequence if violated                                                                                                                                                       |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR-34   | Machine-readable command results are written to `stdout` only. Written via `sys.stdout.write`, never through Rich, never interleaved with stderr content.                    | Downstream scrapers that consume `bpetite encode` output break when stdout contains any bytes other than the JSON array. The contract is byte-exact.                          |
| FR-33   | CLI errors are written to `stderr` and return non-zero exit codes. Every runtime failure catches a specific exception type and routes through `_fail` to `sys.exit(1)`.      | Uncaught exceptions print a Python traceback to stderr. The channel is still correct, but stack frames leak internal implementation state.                                    |
| FR-32   | The CLI exposes the explicit subcommand set `train`, `encode`, `decode`. Subparsers are `required=True`; invoking bare `bpetite` exits with argparse's standard code 2.      | A missing subcommand silently dispatches nothing and exits 0, hiding misconfiguration from CI and shell scripts.                                                              |
| FR-30   | `Tokenizer.train(corpus, vocab_size)` is the pinned public signature. The progress callback must not be added to this method.                                                | Adding a `progress` keyword argument to the public method rewrites the public API contract; every published artifact and every downstream user pins on the current signature. |
| (local) | Subprocess tests invoke `Path(sys.executable).parent / "bpetite"` directly, not `uv run bpetite`.                                                                            | A nested `uv run` layer triggers a second venv resolution that can emit stderr warnings, deadlock under certain OS conditions, and slow the suite unnecessarily.              |
| (local) | Every error message on stderr is grep-friendly: title, body message, and optional recovery hint, all as plain text through `render_error` rather than raw Python tracebacks. | Debuggers reading CI logs resort to pattern-matching against traceback lines, which are fragile across Python minor versions.                                                 |

## Walkthrough

### The CLI in one diagram

```
argv
 |
 v
main() in _cli.py
 |
 v
_build_parser() -> ArgumentParser(prog="bpetite") with required subparsers
 |
 v
args = parser.parse_args()
 |
 v
dispatch on args.command:
   train   -> _cmd_train(args)
   encode  -> _cmd_encode(args)
   decode  -> _cmd_decode(args)
 |
 v
subcommand handler does its work and ends with:
   sys.stdout.write(<machine-readable result>)
   sys.stdout.flush()

Everywhere else:
   _ui.render_banner(), _ui.render_kv_box(), _ui.render_error()
   -> Console(stderr=True) -> stderr
```

Only the three `sys.stdout.write` sites at the end of each handler ever touch stdout.
Every other write, including configuration panels, progress lines, the completion panel,
and error panels, routes through `_ui.console`, which is a stderr-only `Console`.

### `train` traced end-to-end

A single `uv run bpetite train --input data/tinyshakespeare.txt --vocab-size 512 --output out.json` invocation runs this sequence:

1. **Argparse.** `main` calls `_build_parser().parse_args()`. The `train` subparser is
   required, so missing `--input`, `--vocab-size`, or `--output` triggers argparse's
   default exit code 2 with a usage message on stderr. The CLI does not override this.
2. **Dispatch.** `main` dispatches on `args.command == "train"` and calls `_cmd_train`.
3. **Banner + configuration panel (stderr).** `_cmd_train` calls `render_banner()` and
   then `render_kv_box` with the four configured values (input path, vocab size, output
   path, force flag). Both render to the shared stderr `Console`. The banner only
   appears when the terminal is fully interactive and at least 95 columns wide; see
   [Rich Presentation Layer](rich-presentation.md) for the gating rules.
4. **Output path preflight.** `_check_output_path` fails fast if the destination exists
   without `--force`, or if its parent directory is missing. Both failures route through
   `_fail` and exit 1 before any training work starts.
5. **Corpus read.** `_read_corpus_or_exit(args.input)` reads the file as bytes and
   decodes as strict UTF-8. `FileNotFoundError`, `OSError`, and `UnicodeDecodeError` each
   route to a distinct `_fail` message on stderr.
6. **Trainer span starts.** `t0 = time.perf_counter()` at `_cli.py:112`. This is the
   boundary of `elapsed_ms` (see `trainer span` in the index vocabulary).
7. **`_train_with_progress` with callback.** The CLI calls `_train_with_progress`, which
   invokes internal `train_bpe` with a local closure that renders each `ProgressEvent`
   as a plain styled `console.print` line on stderr. See the progress-callback section
   below for the full wiring rationale.
8. **Trainer span ends.** `elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)` at
   `_cli.py:114`. The timer stops immediately after training and before any artifact
   save.
9. **`Tokenizer` wrap.** The `TrainerResult` is packed into a `Tokenizer` via the
   existing constructor (`Tokenizer(vocab=..., merges=..., special_tokens=...)`). No
   separate classmethod is needed because the constructor already accepts the raw
   state; see [Public Tokenizer API](../phase-3/public-api.md#delegation-not-reimplementation)
   for why the class ships a single wrapping path.
10. **Atomic save.** `_save_or_exit(tokenizer, args.output, overwrite=bool(args.force))`
    delegates to `_persistence.save`. `FileExistsError`, `FileNotFoundError`, and
    generic `OSError` each route to a distinct `_fail` message.
11. **Completion panel (stderr).** `render_kv_box` with a green border renders the final
    summary panel: corpus bytes, requested vocab size, actual mergeable vocab size,
    special-token count, elapsed ms, saved path.
12. **JSON summary (stdout).** The one machine-readable write:
    `sys.stdout.write(json.dumps(summary) + "\n"); sys.stdout.flush()`. Five keys,
    default JSON separators, one trailing newline.

Every step between 1 and 12 that renders anything does so on stderr. The only stdout
write is step 12.

### Machine-readable output shapes

The three subcommands each emit exactly one machine-readable payload. The exact shape
matters because downstream tooling pins against it.

**`train`.** A JSON object with five required keys:

```json
{
  "corpus_bytes": 1115394,
  "requested_vocab_size": 512,
  "actual_mergeable_vocab_size": 512,
  "special_token_count": 1,
  "elapsed_ms": 4620.24
}
```

- `corpus_bytes` (int): UTF-8 byte length of the input corpus.
- `requested_vocab_size` (int): the `--vocab-size` value passed on the command line.
- `actual_mergeable_vocab_size` (int): the learned mergeable vocabulary size after
  training. Equals `256 + len(merges)`. May be smaller than `requested_vocab_size` if
  early-stop fired.
- `special_token_count` (int): number of reserved special tokens. Always `1` in v1
  (exactly `<|endoftext|>`).
- `elapsed_ms` (float): trainer span in milliseconds, rounded to two decimal places.
  Wraps only `_train_with_progress`. **Not** the command wall clock; see
  [Benchmark Harness](benchmark-harness.md#the-elapsed_ms-scope-distinction).

The JSON uses default separators (`, ` and `: `). Default separators are intentional: a
five-field object is readable to a human scanning CI logs, and the outer contract is key
presence and types, not byte-exact compactness.

**`encode`.** A compact JSON array of token ids:

```json
[72, 408, 111, 44, 263, 270, 312, 33]
```

The compactness is byte-exact: `json.dumps(ids, separators=(",", ":"))`. No spaces, no
trailing newline beyond the one the CLI appends. Downstream code calling
`json.loads(result.stdout)` parses this directly.

**`decode`.** Raw decoded text, written with `sys.stdout.write(text)`:

```
Hello, world!
```

No JSON wrapper, no label, no trailing newline added beyond what the original decoded
text contained. If the decoded text ended with `\n` (because the token sequence encoded
one), that newline is preserved. Otherwise the output ends without a newline.

### Progress-callback wiring

The `train` subcommand needs a way to render progress output without adding a callback
parameter to public `Tokenizer.train`. FR-30 pins the public method to the exact
signature `(corpus, vocab_size)`, so the callback lives on internal `train_bpe` instead.

`bpetite._trainer` exposes two relevant symbols: the `ProgressEvent` frozen dataclass
and the `train_bpe` function with the keyword-only `progress` parameter.

```python
# src/bpetite/_trainer.py

@dataclass(frozen=True, slots=True)
class ProgressEvent:
    kind: Literal["start", "merge", "complete"]
    merges_completed: int
    merges_planned: int


type ProgressCallback = Callable[[ProgressEvent], None]


def train_bpe(
    corpus: str,
    vocab_size: int,
    *,
    progress: ProgressCallback | None = None,
) -> TrainerResult: ...
```

The three event kinds fire at three specific points in `_trainer.py`:

- `"start"` fires once before the merge loop begins. `merges_planned` equals
  `vocab_size - 256`; `merges_completed` equals `0`.
- `"merge"` fires every time `(step + 1) % _PROGRESS_EVERY == 0`, where
  `_PROGRESS_EVERY = 100`. Practically: after merges 100, 200, 300, and so on.
  `merges_completed` equals `step + 1` at the moment of emission.
- `"complete"` fires once after the loop exits, including when the trainer early-stops
  because `pair_counts` became empty. On early-stop,
  `merges_completed < merges_planned`.

The CLI wires the callback inside `_train_with_progress` in `_cli.py`:

```python
# src/bpetite/_cli.py

def _train_with_progress(corpus: str, vocab_size: int) -> TrainerResult:
    def _on_event(event: ProgressEvent) -> None:
        if event.kind == "start":
            console.print(
                f"[info]Training started: planned={event.merges_planned}[/info]"
            )
        elif event.kind == "merge":
            console.print(
                f"[info]Training merges: {event.merges_completed}"
                f" / {event.merges_planned}[/info]"
            )
        else:  # complete
            console.print(
                f"[success]Training complete: merges={event.merges_completed}[/success]"
            )

    try:
        return train_bpe(corpus, vocab_size, progress=_on_event)
    except ValueError as exc:
        _fail(
            title="Invalid vocab size",
            message=str(exc),
            hint="--vocab-size must be at least 256.",
        )
```

Three observations on this wiring:

- **Public `Tokenizer.train` is not called at all.** The handler calls `train_bpe`
  directly, catches the `ValueError` that invalid vocab sizes raise, and constructs a
  `Tokenizer` from the returned `TrainerResult` with the existing constructor. Public
  `Tokenizer.train` remains the user-facing entry point for library callers who do not
  need a callback.
- **The callback is plain `console.print`, not a Rich `Progress` bar.** An earlier
  design used `rich.progress.Progress` with a lazy `TaskID`; it broke on zero-merge
  runs, early-stop runs, and invalid-vocab runs. The full design decision is at
  [Rich Presentation Layer](rich-presentation.md#the-progress-surface-decision).
- **Each lifecycle line uses a uniquely anchored substring.** The lifecycle line for
  the complete event is `"Training complete: merges={N}"`. The completion panel title
  is also `"Training complete"`. A test that asserts only on `"Training complete"`
  would pass even if the lifecycle line were deleted, because the panel title still
  matches. The contract test uses the longer `"Training complete: merges="` substring
  specifically to anchor on the lifecycle line and catch that regression class.

### Exit code taxonomy

| Exit code | Condition                                                                            | Source                                                                                                                                 |
| --------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| `0`       | Subcommand completed successfully; machine-readable payload on stdout                | Normal return from the subcommand handler                                                                                              |
| `1`       | Runtime failure caught by an explicit `except` clause                                | `_fail` wrapper; every branch in `_read_corpus_or_exit`, `_load_model_or_exit`, `_save_or_exit`, `_train_with_progress`, `_cmd_decode` |
| `2`       | Argparse usage error (missing required argument, unknown subcommand, malformed flag) | Argparse default, not overridden                                                                                                       |

The CLI never raises uncaught exceptions out of `main`. Every known failure type has a
named `except` clause that routes through `_fail` to `render_error` on stderr and
`sys.exit(1)`. The error panel is always structured as a title, a body message, and an
optional recovery hint, so CI log readers can grep for any of the three fields.

### Subprocess-level contract tests

`tests/test_cli.py` is the enforcement layer. It does not import `_cli`; it drives the
installed console entry point through `subprocess.run` and captures both streams. This
preserves the channel boundary that in-process imports would collapse.

**The executable.** `_cli_executable()` resolves `Path(sys.executable).parent / "bpetite"`
(`test_cli.py:37-45`), which points directly at the venv's installed console script. Two
properties matter: it is a deterministic absolute path under `uv run pytest` on both
macOS and Linux, and it avoids a nested `uv run` wrapper that would trigger a second
venv resolution step inside the already-active venv.

**Session fixtures.** The test suite uses two session-scoped fixtures to keep expensive
operations from running per test:

- `cli_trained_artifact`: trains a tokenizer at `vocab_size=260` against
  `tests/fixtures/tiny.txt` exactly once per session. Every `encode` and `decode` test
  reuses this artifact.
- `progress_corpus_path`: writes a deterministic synthetic ~15 KB corpus seeded with
  `random.Random(0xBADC0FFEE)`. 2500 random ASCII words with enough distinct bigrams
  that training to `vocab_size=480` (224 planned merges) completes fully and fires the
  `"merge"` event at least twice. Ordinary fixtures cannot do this. `tests/fixtures/
tiny.txt` completes in far fewer than 100 merges and never trips the every-100-merges
  callback branch.

**Channel-separation assertion pattern.** Every test asserts both streams. On success:

```python
result = _run_cli("encode", "--model", str(cli_trained_artifact), "--text", "Hello")
assert result.returncode == 0
ids = json.loads(result.stdout)       # stdout: valid JSON, nothing else
assert isinstance(ids, list)
assert all(isinstance(i, int) for i in ids)
# stderr assertions: either empty, or does not contain JSON-key substrings
```

On failure, the inverse:

```python
result = _run_cli("encode", "--model", "nonexistent.json", "--text", "x")
assert result.returncode != 0
assert result.stdout == ""            # nothing leaked to stdout on failure
assert len(result.stderr) > 0         # error message reached stderr
```

Some tests go further and assert that specific JSON key substrings (`'"corpus_bytes":'`,
`'"elapsed_ms":'`, and so on) are absent from stderr, guarding against a double-write
regression where the CLI accidentally prints its summary to both channels.

## Failure modes

| Failure                                         | Exception type / exit code | FR    | Caught by                                                                                                       |
| ----------------------------------------------- | -------------------------- | ----- | --------------------------------------------------------------------------------------------------------------- |
| Machine-readable JSON leaks onto stderr         | `AssertionError` (test)    | FR-34 | `test_train_success_writes_json_summary_on_stdout`                                                              |
| Progress or error text leaks onto stdout        | `AssertionError` (test)    | FR-33 | Every success test that asserts `result.stderr == ""` and every failure test that asserts `result.stdout == ""` |
| Missing input file for `train`                  | exit 1                     | FR-33 | `test_train_fails_on_missing_input`                                                                             |
| Invalid UTF-8 input file for `train`            | exit 1                     | FR-33 | `test_train_fails_on_invalid_utf8_input`                                                                        |
| Output path exists without `--force`            | exit 1                     | FR-33 | `test_train_fails_when_output_exists_without_force`                                                             |
| Unknown token id passed to `decode`             | exit 1                     | FR-33 | `test_decode_fails_on_unknown_token_id`                                                                         |
| Decoded bytes are not valid UTF-8               | exit 1                     | FR-33 | `test_decode_fails_on_invalid_utf8`                                                                             |
| Missing model artifact for `encode` or `decode` | exit 1                     | FR-33 | `test_encode_fails_on_nonexistent_model`, `test_decode_fails_on_nonexistent_model`                              |
| Corrupt or schema-invalid model artifact        | exit 1                     | FR-33 | Error path tested indirectly via `_load_model_or_exit` branch coverage                                          |
| Missing subcommand (`bpetite` alone)            | exit 2                     | FR-32 | Argparse default; covered in `test_no_subcommand_exits_with_usage`                                              |

### Silent failure modes called out by name

Three bugs are easy to miss: they pass ordinary tests and surface only
against specific test shapes. Each is pinned by a dedicated case.

**Every-100-merges branch never fires.** Training at `vocab_size=260` against the
standard tiny fixture completes 4 merges total. The every-100-merges branch in
`_train_with_progress` never runs. A test that uses only the tiny fixture would pass
even if the branch were deleted. `progress_corpus_path` exists specifically to force

> =100 merges: it writes a deterministic synthetic corpus, the test runs with
> `--vocab-size 480` to plan 224 merges, and the assertion on `"Training merges:"`
> substring in stderr proves the branch fired. Deterministic seed (`random.Random(0xBADC0FFEE)`)
> means the event count is reproducible across machines and runs.

**Double-anchored substring matches two rendering surfaces.** The lifecycle line for
the `complete` event reads `Training complete: merges={N}` through `console.print`.
The completion panel title is `Training complete`. A test asserting only on the bare
substring `"Training complete"` would pass even if the entire `else: # complete` branch
in `_train_with_progress` were deleted, because the panel title would still match.
The contract test asserts on `"Training complete: merges="` (note the colon and
field label) specifically to anchor on the lifecycle line, not the panel title.

**Double-write regression.** An implementation that writes the `train` JSON summary to
both stdout (via `sys.stdout.write`) and stderr (accidentally, through a stray
`console.print(json.dumps(...))`) still satisfies a bare `returncode == 0` plus
`json.loads(result.stdout)` assertion. The contract test additionally asserts that
every key substring (`'"corpus_bytes":'`, `'"requested_vocab_size":'`,
`'"actual_mergeable_vocab_size":'`, `'"special_token_count":'`, `'"elapsed_ms":'`) is
absent from stderr, catching this class of regression.

## Related reading

- [Rich Presentation Layer](rich-presentation.md): the shared stderr `Console`, the
  themed palette, and the full design decision behind plain `console.print` lifecycle
  lines instead of a live `rich.progress.Progress` bar.
- [Benchmark Harness](benchmark-harness.md): the `elapsed_ms` trainer span
  distinction, cross-linked from the `train` JSON summary discussion above.
- [Phase 3 Public Tokenizer API](../phase-3/public-api.md): the five-method contract
  the CLI wraps; why the CLI bypasses `Tokenizer.train` for the callback-enabled path.
- [Phase 2 Core Algorithm](../phase-2/core-algorithm.md): the trainer the CLI drives;
  the early-stop behavior that produces `actual_mergeable_vocab_size < requested_vocab_size`.
- [`README.md`](../../README.md): user-facing CLI examples with captured real outputs.
- [`docs/bpetite-prd-v2.md`](../bpetite-prd-v2.md): FR-30, FR-32, FR-33, FR-34, FR-35,
  FR-36.
- [`src/bpetite/_cli.py`](../../src/bpetite/_cli.py): full CLI implementation.
- [`src/bpetite/_trainer.py`](../../src/bpetite/_trainer.py): `ProgressEvent` and
  `train_bpe(corpus, vocab_size, *, progress)`.
- [`tests/test_cli.py`](../../tests/test_cli.py): subprocess-level contract tests and
  both session-scoped fixtures.
