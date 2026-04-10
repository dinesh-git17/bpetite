---
name: cli-contract
description: "Enforces the bpetite CLI output contract: stdout/stderr channel discipline, exit codes, exact output formats, progress callback wiring, and argparse patterns. Use this skill whenever working on _cli.py, test_cli.py, or any task involving CLI output, argparse setup, subcommands, stdout, stderr, train/encode/decode commands, progress output, or channel separation. Auto-invoke when the user mentions CLI, command line, argparse, stdout, stderr, subcommand, train command, encode command, decode command, progress callback, or exit code in the context of bpetite. FR-33 and FR-34 are strict: a single print() that lands on the wrong channel will fail a CLI smoke test."
---

# bpetite CLI Contract

This skill encodes all non-negotiable rules for `src/bpetite/_cli.py` and
`tests/test_cli.py`. Every rule below is derived directly from FR-33, FR-34,
and the task-list acceptance criteria for Tasks 4-1 and 4-2. Deviating from
any of these rules will produce a test failure or a broken reviewer experience.

---

## 1. Channel Discipline — The One Rule That Breaks Everything

**Machine-readable output → `sys.stdout` only.**
**Human-readable messages, errors, and progress → `sys.stderr` only.**

There is no exception to this rule. A bare `print()` defaults to stdout.
Every message that is not a machine-readable result must use
`print(..., file=sys.stderr)`.

| What                        | Channel                                       |
| --------------------------- | --------------------------------------------- |
| `encode` JSON array         | `stdout`                                      |
| `decode` raw text           | `stdout`                                      |
| `train` JSON summary object | `stdout`                                      |
| Training progress lines     | `stderr`                                      |
| All error messages          | `stderr`                                      |
| argparse usage/error output | `stderr` (argparse default — do not override) |

CLI smoke tests check stdout content directly. Any progress line or error
message that leaks onto stdout will break the assertion.

---

## 2. Exit Codes

Non-zero exit on **every** error condition. Known conditions and their handling:

| Condition                               | Action                                             |
| --------------------------------------- | -------------------------------------------------- |
| Missing input file                      | `sys.exit(1)` after printing to stderr             |
| Invalid UTF-8 input file                | `sys.exit(1)` after printing to stderr             |
| Save to existing path without `--force` | `sys.exit(1)` after catching `FileExistsError`     |
| Unknown token ID in decode              | `sys.exit(1)` after catching `KeyError`            |
| Invalid UTF-8 bytes in decode           | `sys.exit(1)` after catching `UnicodeDecodeError`  |
| Missing parent directory for save       | `sys.exit(1)` after catching `FileNotFoundError`   |
| argparse argument error                 | Exit code `2` (argparse default — do not override) |

Use explicit `try/except` for every library call that can raise a typed
exception. Do not let unhandled exceptions bubble up to a traceback — catch
the specific exception, print a grep-friendly message to stderr, and exit 1.

---

## 3. Encode Output Format

`encode` writes a compact JSON array to stdout. No trailing newline is
required beyond what `print` adds naturally.

```python
import json, sys

ids: list[int] = tokenizer.encode(text)
print(json.dumps(ids, separators=(",", ":")), file=sys.stdout)
```

`separators=(",", ":")` is mandatory. The compact form produces
`[72,101,108,108,111]`, not `[72, 101, 108, 108, 111]`. The smoke test
checks for this exact format.

Do **not** pretty-print, add newlines between elements, or wrap the array
in any outer object or string.

---

## 4. Decode Output Format

`decode` writes raw decoded text to stdout. No JSON wrapper, no label, no
trailing metadata.

```python
text: str = tokenizer.decode(ids)
print(text, file=sys.stdout, end="")
```

Use `end=""` to avoid appending a newline that was not part of the original
decoded text. The smoke test checks stdout content byte-for-byte.

If the decoded text already ends with a newline (because the token sequence
encoded one), that newline prints naturally. Do not add an extra one.

---

## 5. Train JSON Summary

`train` writes exactly one JSON object to stdout after training completes.
The object must contain exactly these keys in any order:

```python
import json, sys, time

summary = {
    "corpus_bytes": len(corpus.encode("utf-8")),
    "requested_vocab_size": vocab_size,
    "actual_mergeable_vocab_size": tokenizer._mergeable_vocab_size,  # internal attr
    "special_token_count": len(tokenizer._special_tokens),           # internal attr
    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
}
print(json.dumps(summary), file=sys.stdout)
```

No extra keys. No trailing text. The smoke test parses this JSON and checks
field presence and types.

`elapsed_ms` is a float rounded to 2 decimal places. All other fields are
integers.

---

## 6. Training Progress Output

Progress must be written to stderr only, never stdout. The callback-based
approach is described in Section 7; this section covers the output format.

Required progress events and their stderr format:

```
Training started: vocab_size=512, corpus_bytes=1234567
Merges completed: 50
Merges completed: 100
Merges completed: 150
...
Training complete: actual_mergeable_vocab_size=512, elapsed_ms=4201.33
```

Emit a "Merges completed" line at start (0), every 100 merges, and at
completion. The exact wording is flexible but must be human-readable and
grep-friendly. Do not use JSON for progress lines.

---

## 7. Progress Callback Pattern — The Non-Obvious Wiring

The public `Tokenizer.train(corpus: str, vocab_size: int)` signature must
**not** expose a `progress_callback` parameter. The PRD API contract is
fixed: exactly `corpus` and `vocab_size`.

The callback is threaded through internal functions only.

### Internal trainer function signature

In `src/bpetite/_trainer.py`, the internal training entry point accepts an
optional callback:

```python
from typing import Callable

def _run_training(
    corpus: str,
    vocab_size: int,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[dict[int, bytes], list[tuple[int, int]], dict[str, int]]:
    ...
```

The callback signature is `(merges_done: int, target_merges: int) -> None`.
The caller (CLI) provides the callback; the library default is `None`.

### Wiring in `_cli.py`

```python
import sys, time
from bpetite import Tokenizer
from bpetite._trainer import _run_training  # internal import — CLI only

def _progress(done: int, total: int) -> None:
    if done == 0:
        print(f"Training started: target_merges={total}", file=sys.stderr)
    elif done % 100 == 0:
        print(f"Merges completed: {done}", file=sys.stderr)

# CLI calls the internal function directly to inject the callback,
# then constructs a Tokenizer from the returned state.
```

The public `Tokenizer.train` calls `_run_training` internally with
`progress_callback=None`. The CLI bypasses the public method and calls
`_run_training` directly, then wraps the result in a `Tokenizer` instance
via a private constructor or `load`-equivalent path.

If the `Tokenizer` class has a private `_from_state` classmethod or
equivalent for constructing from raw vocab/merges/special_tokens, use that.
If it does not exist yet, add it as an internal helper (underscore-prefixed,
not part of the public API contract).

### Why the callback cannot go on `Tokenizer.train`

FR-30 enumerates exactly five public methods. Adding `progress_callback` to
`Tokenizer.train` would change the public API contract. The CLI is the only
caller that needs progress output; the library should remain clean.

---

## 8. argparse Patterns

Use stdlib `argparse` only. No click, no typer, no third-party argument
parsers.

### Subcommand structure

```python
import argparse

def main() -> None:
    parser = argparse.ArgumentParser(prog="bpetite")
    sub = parser.add_subparsers(dest="command", required=True)

    # train
    p_train = sub.add_parser("train")
    p_train.add_argument("--input", required=True)
    p_train.add_argument("--vocab-size", type=int, required=True)
    p_train.add_argument("--output", required=True)
    p_train.add_argument("--force", action="store_true")

    # encode
    p_enc = sub.add_parser("encode")
    p_enc.add_argument("--model", required=True)
    p_enc.add_argument("--text", required=True)

    # decode
    p_dec = sub.add_parser("decode")
    p_dec.add_argument("--model", required=True)
    p_dec.add_argument("--ids", nargs="+", type=int, required=True)

    args = parser.parse_args()
    ...
```

### Critical `--ids` pattern

`--ids` must use `nargs="+"` with `type=int`. This allows the CLI to accept
space-separated integer token IDs:

```
uv run bpetite decode --model tokenizer.json --ids 72 101 108 108 111
```

Do **not** use `nargs="*"` (permits zero arguments), `type=str` (requires
manual int conversion), or a comma-separated single string (breaks the CLI
contract example in the PRD).

### `--force` maps to `overwrite`

The CLI flag is `--force`; the `Tokenizer.save` parameter is `overwrite`.
Map explicitly:

```python
tokenizer.save(args.output, overwrite=args.force)
```

---

## 9. UTF-8 File Read Pattern

`train` reads the input file with strict UTF-8 decoding. Fail fast on invalid
bytes — no replacement characters, no silent coercion.

```python
try:
    with open(args.input, "r", encoding="utf-8", errors="strict") as f:
        corpus = f.read()
except FileNotFoundError as e:
    print(f"Error: input file not found: {args.input}", file=sys.stderr)
    sys.exit(1)
except UnicodeDecodeError as e:
    print(f"Error: input file contains invalid UTF-8: {e}", file=sys.stderr)
    sys.exit(1)
```

---

## 10. Test Patterns for `test_cli.py`

CLI tests must invoke the installed console entry point via subprocess, not
by importing `_cli` directly. This validates the real installed path and
preserves stdout/stderr separation.

```python
import subprocess, json, sys
from pathlib import Path

def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "bpetite", *args],
        capture_output=True,
        text=True,
    )
```

### Channel separation assertions

```python
result = run_cli("encode", "--model", str(model_path), "--text", "Hello")
assert result.returncode == 0
ids = json.loads(result.stdout)       # stdout: JSON array
assert result.stderr == ""            # nothing leaked to stderr on success
```

For error cases, assert the **inverse**:

```python
result = run_cli("encode", "--model", "nonexistent.json", "--text", "x")
assert result.returncode != 0
assert result.stdout == ""            # nothing leaked to stdout on failure
assert len(result.stderr) > 0        # error message is on stderr
```

### Required test coverage for `test_cli.py`

- Successful `train`: returncode 0, stdout parses as JSON with required keys,
  no machine-readable output on stderr.
- Successful `encode`: returncode 0, stdout is compact JSON array, stderr empty.
- Successful `decode`: returncode 0, stdout is raw text, stderr empty.
- `train` nonexistent input file: returncode nonzero, stdout empty.
- `train` invalid UTF-8 input (`invalid_utf8.bin`): returncode nonzero,
  stdout empty.
- `train` save without `--force` to existing path: returncode nonzero,
  stdout empty.
- `train` save with `--force` to existing path: returncode 0.
- `decode` unknown token ID: returncode nonzero, stdout empty.
- `decode` token sequence producing invalid UTF-8: returncode nonzero,
  stdout empty.
- `train` progress lines appear on stderr (check `"Merges"` or equivalent
  substring in stderr when training completes at least one merge).
- `encode` output uses compact separators (no spaces in JSON array).

---

## 11. Quick Checklist Before Submitting `_cli.py`

Run through this mentally before calling a CLI implementation done:

- [ ] Every `print()` that is not a machine-readable result uses `file=sys.stderr`.
- [ ] `encode` uses `json.dumps(ids, separators=(",", ":"))`.
- [ ] `decode` uses `end=""` and writes to stdout.
- [ ] `train` summary JSON has exactly the five required keys.
- [ ] Progress lines go to stderr, never stdout.
- [ ] `--ids` uses `nargs="+"` and `type=int`.
- [ ] `--force` maps to `overwrite=args.force` on `save`.
- [ ] All known exception types are caught and result in `sys.exit(1)`.
- [ ] argparse errors exit with code 2 (default, do not override).
- [ ] `progress_callback` is not on `Tokenizer.train`'s public signature.
- [ ] CLI imports `_run_training` from `bpetite._trainer` for callback wiring.
