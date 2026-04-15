"""Command-line interface for the bpetite tokenizer.

Exposes three subcommands — ``train``, ``encode``, and ``decode`` — wired
into a single ``main`` entry point advertised as the ``bpetite`` console
script in ``pyproject.toml``.

Channel discipline is the one rule that matters everywhere in this module:

* Every machine-readable result (``train`` JSON summary, ``encode`` compact
  JSON array, ``decode`` raw text) is written with ``sys.stdout.write`` so
  no Rich markup or theming can bleed into the stdout contract fixed by
  FR-33 and FR-34.
* Every human-readable element (banner, configuration panels, progress
  bars, completion summaries, error messages) is routed through the
  shared stderr :class:`~bpetite._ui.console`.

The progress callback for training is threaded through the internal
:func:`bpetite._trainer.train_bpe` entry point rather than the public
``Tokenizer.train`` method: FR-30 pins the public method signature to
``(corpus, vocab_size)`` exactly, so the callback wiring lives in the CLI.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import NoReturn

from bpetite import Tokenizer
from bpetite._trainer import ProgressEvent, TrainerResult, train_bpe
from bpetite._ui import (
    console,
    is_fully_interactive,
    render_banner,
    render_error,
    render_kv_box,
)

_TEXT_PREVIEW_LIMIT = 80


def main() -> None:
    """Parse arguments and dispatch to the selected subcommand."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "train":
        _cmd_train(args)
    elif args.command == "encode":
        _cmd_encode(args)
    elif args.command == "decode":
        _cmd_decode(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bpetite",
        description="Deterministic byte-level BPE tokenizer.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_train = sub.add_parser("train", help="Train a BPE tokenizer from a corpus.")
    p_train.add_argument("--input", required=True, help="UTF-8 training corpus path.")
    p_train.add_argument(
        "--vocab-size",
        type=int,
        required=True,
        help="Target mergeable vocabulary size (>= 256).",
    )
    p_train.add_argument("--output", required=True, help="Artifact destination path.")
    p_train.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output artifact if it already exists.",
    )

    p_enc = sub.add_parser("encode", help="Encode text into a token id sequence.")
    p_enc.add_argument("--model", required=True, help="Schema v1 artifact path.")
    p_enc.add_argument("--text", required=True, help="UTF-8 text to encode.")

    p_dec = sub.add_parser("decode", help="Decode token ids into text.")
    p_dec.add_argument("--model", required=True, help="Schema v1 artifact path.")
    p_dec.add_argument(
        "--ids",
        nargs="+",
        type=int,
        required=True,
        help="Space-separated token ids.",
    )

    return parser


def _cmd_train(args: argparse.Namespace) -> None:
    render_banner()
    render_kv_box(
        rows=[
            ("Input", str(args.input)),
            ("Vocab size", str(args.vocab_size)),
            ("Output", str(args.output)),
            ("Force overwrite", "yes" if args.force else "no"),
        ],
        title="Training",
    )

    _check_output_path(args.output, force=bool(args.force))

    corpus = _read_corpus_or_exit(args.input)
    corpus_bytes = len(corpus.encode("utf-8"))

    t0 = time.perf_counter()
    result = _train_with_progress(corpus, args.vocab_size)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

    tokenizer = Tokenizer(
        vocab=dict(result.vocab),
        merges=list(result.merges),
        special_tokens=dict(result.special_tokens),
    )
    _save_or_exit(tokenizer, args.output, overwrite=bool(args.force))

    render_kv_box(
        rows=[
            ("Corpus bytes", f"{corpus_bytes:,}"),
            ("Requested vocab size", str(args.vocab_size)),
            ("Actual mergeable vocab size", str(result.mergeable_vocab_size)),
            ("Special tokens", str(len(result.special_tokens))),
            ("Elapsed", f"{elapsed_ms:.2f} ms"),
            ("Saved to", str(args.output)),
        ],
        title="Training complete",
        border_style="green",
    )

    summary = {
        "corpus_bytes": corpus_bytes,
        "requested_vocab_size": int(args.vocab_size),
        "actual_mergeable_vocab_size": result.mergeable_vocab_size,
        "special_token_count": len(result.special_tokens),
        "elapsed_ms": elapsed_ms,
    }
    sys.stdout.write(json.dumps(summary) + "\n")
    sys.stdout.flush()


def _cmd_encode(args: argparse.Namespace) -> None:
    interactive = is_fully_interactive()
    if interactive:
        render_banner()
        render_kv_box(
            rows=[
                ("Model", str(args.model)),
                ("Text", _truncate(str(args.text), _TEXT_PREVIEW_LIMIT)),
            ],
            title="Encoding",
        )

    tokenizer = _load_model_or_exit(args.model)

    t0 = time.perf_counter()
    ids = tokenizer.encode(args.text)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

    if interactive:
        render_kv_box(
            rows=[
                ("Tokens", str(len(ids))),
                ("Elapsed", f"{elapsed_ms:.2f} ms"),
            ],
            title="Encoded",
            border_style="green",
        )

    sys.stdout.write(json.dumps(ids, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _cmd_decode(args: argparse.Namespace) -> None:
    interactive = is_fully_interactive()
    if interactive:
        render_banner()
        render_kv_box(
            rows=[
                ("Model", str(args.model)),
                ("Token count", str(len(args.ids))),
            ],
            title="Decoding",
        )

    tokenizer = _load_model_or_exit(args.model)

    t0 = time.perf_counter()
    try:
        text = tokenizer.decode(args.ids)
    except KeyError as exc:
        _fail(
            title="Unknown token id",
            message=f"Token id {exc.args[0]} is not in the model's vocabulary.",
            hint="Every id passed to --ids must exist in the loaded model.",
        )
    except UnicodeDecodeError as exc:
        _fail(
            title="Invalid UTF-8 in decode",
            message=f"Decoded bytes are not valid UTF-8: {exc}",
            hint="This token sequence is incomplete or does not form valid text.",
        )
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

    if interactive:
        render_kv_box(
            rows=[
                ("Characters", str(len(text))),
                ("Elapsed", f"{elapsed_ms:.2f} ms"),
            ],
            title="Decoded",
            border_style="green",
        )

    sys.stdout.write(text)
    sys.stdout.flush()


def _check_output_path(path: str, *, force: bool) -> None:
    """Fail fast if the destination is already blocking the save.

    Both checks are cheaply verifiable before training starts. Running them
    up-front prevents spending minutes on a training pass only to discover
    that the ``--output`` path was already taken or its parent directory
    was missing. The save call at the end of ``train`` still catches the
    same conditions as a safety net for race conditions.
    """
    output_path = Path(path)
    if output_path.exists() and not force:
        _fail(
            title="Save blocked",
            message=f"{path} already exists.",
            hint="Re-run with --force to overwrite, or choose a different --output.",
        )
    if not output_path.parent.exists():
        _fail(
            title="Save failed",
            message=f"Parent directory of {path} does not exist.",
            hint="Create the parent directory before running train.",
        )


def _read_corpus_or_exit(path: str) -> str:
    try:
        return Path(path).read_bytes().decode("utf-8")
    except FileNotFoundError:
        _fail(
            title="Input not found",
            message=f"No such file: {path}",
            hint="Check the --input path and try again.",
        )
    except OSError as exc:
        _fail(
            title="Input unreadable",
            message=f"Cannot read {path}: {exc}",
            hint="Check that --input is a regular file and you have read permission.",
        )
    except UnicodeDecodeError as exc:
        _fail(
            title="Invalid UTF-8 corpus",
            message=f"{path} is not valid UTF-8: {exc}",
            hint="bpetite reads training corpora with strict UTF-8 decoding.",
        )


def _train_with_progress(corpus: str, vocab_size: int) -> TrainerResult:
    """Run ``train_bpe`` with plain styled lifecycle lines on stderr.

    The callback emits three kinds of lines on the shared stderr
    ``Console``, matching the task-list requirement that ``train`` write
    progress updates at start, every 100 completed merges, and
    completion. Rich ``Progress`` is intentionally not used: its live
    display produced subtle rendering errors on zero-merge runs,
    early-stop runs, and invalid-vocab runs. Plain ``console.print``
    lines sidestep every edge case while still rendering beautifully
    through the themed console.
    """

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


def _save_or_exit(tokenizer: Tokenizer, path: str, *, overwrite: bool) -> None:
    try:
        tokenizer.save(path, overwrite=overwrite)
    except FileExistsError:
        _fail(
            title="Save blocked",
            message=f"{path} already exists.",
            hint="Re-run with --force to overwrite.",
        )
    except FileNotFoundError:
        _fail(
            title="Save failed",
            message=f"Parent directory of {path} does not exist.",
            hint="Create the parent directory before running train.",
        )
    except OSError as exc:
        _fail(
            title="Save failed",
            message=f"Cannot write {path}: {exc}",
            hint="Check filesystem permissions and that --output is not a directory.",
        )


def _load_model_or_exit(path: str) -> Tokenizer:
    try:
        return Tokenizer.load(path)
    except FileNotFoundError:
        _fail(
            title="Model not found",
            message=f"No such file: {path}",
            hint="Pass --model pointing at a Schema v1 artifact.",
        )
    except OSError as exc:
        _fail(
            title="Model unreadable",
            message=f"Cannot read {path}: {exc}",
            hint="Check that --model is a regular file and you have read permission.",
        )
    except (KeyError, ValueError) as exc:
        _fail(
            title="Model load failed",
            message=str(exc),
            hint=f"Verify {path} is a valid Schema v1 bpetite artifact.",
        )


def _fail(*, title: str, message: str, hint: str | None = None) -> NoReturn:
    render_error(title=title, message=message, hint=hint)
    sys.exit(1)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


if __name__ == "__main__":
    main()
