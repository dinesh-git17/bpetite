"""Subprocess-level contract tests for the ``bpetite`` CLI.

Covers every acceptance criterion for Task 4-2: successful ``train``,
``encode``, and ``decode`` runs; every runtime failure mode the CLI
catches (missing input, invalid UTF-8 input, existing output without
``--force``, unknown decode id, invalid decoded bytes); and strict
channel separation — machine-readable results never leak onto stderr,
and error messages never leak onto stdout.

Tests invoke the installed ``bpetite`` console entry point via
``subprocess.run`` rather than importing ``_cli`` directly. This
exercises the real installed path that CI smoke tests will hit, and
preserves the stdout/stderr boundary that in-process imports would
collapse.
"""

import json
import random
import string
import subprocess
import sys
from pathlib import Path

import pytest

_REQUIRED_SUMMARY_KEYS: frozenset[str] = frozenset(
    {
        "corpus_bytes",
        "requested_vocab_size",
        "actual_mergeable_vocab_size",
        "special_token_count",
        "elapsed_ms",
    }
)


def _cli_executable() -> str:
    """Return the absolute path to the installed ``bpetite`` console script.

    The venv's ``bin`` directory sits next to ``sys.executable`` in every
    uv-managed environment, so this resolves deterministically under
    ``uv run pytest`` on both supported OS targets without shelling out
    through a second ``uv run`` layer.
    """
    return str(Path(sys.executable).parent / "bpetite")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [_cli_executable(), *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session")
def progress_corpus_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Write a deterministic synthetic corpus that supports >=100 merges.

    The tiny/unicode fixtures early-stop well before 100 merges because
    they lack distinct byte-pair variety, so they cannot drive the
    every-100-merges ``console.print`` branch in ``_cmd_train``'s
    progress callback. This fixture produces ~15 KB of fixed-seed
    random ASCII "words" with enough distinct bigrams that training to
    ``vocab_size=480`` (224 planned merges) completes fully and emits
    at least one ``kind="merge"`` event. Deterministic via the pinned
    ``random.Random`` seed so the event count is reproducible run to
    run.
    """
    rng = random.Random(0xBADC0FFEE)  # noqa: S311
    alphabet = string.ascii_lowercase
    words = ["".join(rng.choices(alphabet, k=rng.randint(3, 7))) for _ in range(2500)]
    corpus = " ".join(words)

    corpus_dir = tmp_path_factory.mktemp("cli_progress_corpus")
    corpus_path = corpus_dir / "synthetic.txt"
    corpus_path.write_text(corpus, encoding="utf-8")
    return corpus_path


@pytest.fixture(scope="session")
def cli_trained_artifact(
    tmp_path_factory: pytest.TempPathFactory,
    tiny_corpus_path: Path,
) -> Path:
    """Train a tokenizer via the CLI once per session and return its path.

    Downstream encode/decode tests reuse this artifact so the expensive
    subprocess ``train`` call happens exactly once regardless of how
    many cases parametrize against it.
    """
    artifact_dir = tmp_path_factory.mktemp("cli_trained")
    artifact = artifact_dir / "tokenizer.json"
    result = _run_cli(
        "train",
        "--input",
        str(tiny_corpus_path),
        "--vocab-size",
        "260",
        "--output",
        str(artifact),
    )
    assert result.returncode == 0, result.stderr
    assert artifact.exists()
    return artifact


def test_train_success_writes_json_summary_on_stdout(
    tmp_path: Path, tiny_corpus_path: Path
) -> None:
    artifact = tmp_path / "tokenizer.json"
    result = _run_cli(
        "train",
        "--input",
        str(tiny_corpus_path),
        "--vocab-size",
        "260",
        "--output",
        str(artifact),
    )
    assert result.returncode == 0
    assert artifact.exists()

    summary = json.loads(result.stdout)
    assert isinstance(summary, dict)
    assert set(summary.keys()) == _REQUIRED_SUMMARY_KEYS
    assert isinstance(summary["corpus_bytes"], int)
    assert isinstance(summary["requested_vocab_size"], int)
    assert isinstance(summary["actual_mergeable_vocab_size"], int)
    assert isinstance(summary["special_token_count"], int)
    assert isinstance(summary["elapsed_ms"], float)
    assert summary["requested_vocab_size"] == 260
    assert summary["corpus_bytes"] == len(tiny_corpus_path.read_bytes())

    expected_json = json.dumps(summary)
    assert expected_json not in result.stderr
    assert '"corpus_bytes":' not in result.stderr
    assert '"requested_vocab_size":' not in result.stderr
    assert '"actual_mergeable_vocab_size":' not in result.stderr
    assert '"special_token_count":' not in result.stderr
    assert '"elapsed_ms":' not in result.stderr


def test_train_progress_lines_land_on_stderr(
    tmp_path: Path, tiny_corpus_path: Path
) -> None:
    """AC1: progress updates appear only on stderr, never on stdout.

    Asserts on the full lifecycle payloads rather than their bare title
    strings. The pre-training configuration panel has the title
    ``"Training"`` and the post-training completion panel has the title
    ``"Training complete"``, so asserting only ``"Training complete"``
    would pass even if the ``complete`` branch of the progress callback
    were deleted. Pinning ``"Training started: planned="`` and
    ``"Training complete: merges="`` — substrings that only the
    lifecycle ``console.print`` lines produce — keeps the assertion
    anchored to the progress callback itself. ANSI escapes, panel
    glyphs, and timings are intentionally not asserted because they are
    unstable across terminals and Rich versions.
    """
    artifact = tmp_path / "tokenizer.json"
    result = _run_cli(
        "train",
        "--input",
        str(tiny_corpus_path),
        "--vocab-size",
        "260",
        "--output",
        str(artifact),
    )
    assert result.returncode == 0
    assert "Training started: planned=" in result.stderr
    assert "Training complete: merges=" in result.stderr
    assert "Training started" not in result.stdout
    assert "Training complete" not in result.stdout


def test_train_progress_emits_every_100_merges_on_stderr(
    tmp_path: Path, progress_corpus_path: Path
) -> None:
    """The every-100-merges progress branch writes to stderr, not stdout.

    Uses the synthetic ``progress_corpus_path`` fixture instead of
    ``tiny_corpus_path`` because the tiny corpus early-stops at ~51
    merges and therefore never triggers the ``(step + 1) % 100 == 0``
    event inside ``_trainer.train_bpe``. With ``--vocab-size 480``
    (224 planned merges) the run completes fully and the progress
    callback fires at least one ``kind="merge"`` event, which
    ``_cmd_train`` routes through the stderr console as a line
    containing ``"Training merges:"``. Without this check the
    corresponding branch in ``_train_with_progress._on_event`` could
    regress silently.
    """
    artifact = tmp_path / "tokenizer.json"
    result = _run_cli(
        "train",
        "--input",
        str(progress_corpus_path),
        "--vocab-size",
        "480",
        "--output",
        str(artifact),
    )
    assert result.returncode == 0
    assert "Training merges:" in result.stderr
    assert "Training merges" not in result.stdout


def test_train_nonexistent_input_fails_without_stdout_leak(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.txt"
    artifact = tmp_path / "tokenizer.json"
    result = _run_cli(
        "train",
        "--input",
        str(missing),
        "--vocab-size",
        "260",
        "--output",
        str(artifact),
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr != ""
    assert not artifact.exists()


def test_train_invalid_utf8_input_fails_without_stdout_leak(
    tmp_path: Path, invalid_utf8_path: Path
) -> None:
    artifact = tmp_path / "tokenizer.json"
    result = _run_cli(
        "train",
        "--input",
        str(invalid_utf8_path),
        "--vocab-size",
        "260",
        "--output",
        str(artifact),
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr != ""
    assert not artifact.exists()


def test_train_save_without_force_to_existing_path_fails(
    tmp_path: Path, tiny_corpus_path: Path
) -> None:
    artifact = tmp_path / "tokenizer.json"
    artifact.write_text("placeholder", encoding="utf-8")
    original_contents = artifact.read_text(encoding="utf-8")

    result = _run_cli(
        "train",
        "--input",
        str(tiny_corpus_path),
        "--vocab-size",
        "260",
        "--output",
        str(artifact),
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr != ""
    assert artifact.read_text(encoding="utf-8") == original_contents


def test_train_save_with_force_to_existing_path_succeeds(
    tmp_path: Path, tiny_corpus_path: Path
) -> None:
    artifact = tmp_path / "tokenizer.json"
    artifact.write_text("placeholder", encoding="utf-8")

    result = _run_cli(
        "train",
        "--input",
        str(tiny_corpus_path),
        "--vocab-size",
        "260",
        "--output",
        str(artifact),
        "--force",
    )
    assert result.returncode == 0

    summary = json.loads(result.stdout)
    assert set(summary.keys()) == _REQUIRED_SUMMARY_KEYS

    reloaded = json.loads(artifact.read_text(encoding="utf-8"))
    assert reloaded != "placeholder"
    assert isinstance(reloaded, dict)


def test_encode_success_writes_compact_json_array_on_stdout_only(
    cli_trained_artifact: Path,
) -> None:
    result = _run_cli(
        "encode",
        "--model",
        str(cli_trained_artifact),
        "--text",
        "Hello, world!",
    )
    assert result.returncode == 0
    assert result.stderr == ""

    body = result.stdout.rstrip("\n")
    ids = json.loads(body)
    assert isinstance(ids, list)
    assert all(isinstance(i, int) for i in ids)
    assert len(ids) > 0

    assert " " not in body
    assert body == json.dumps(ids, separators=(",", ":"))


def test_decode_success_writes_raw_text_on_stdout_only(
    cli_trained_artifact: Path,
) -> None:
    encode_result = _run_cli(
        "encode",
        "--model",
        str(cli_trained_artifact),
        "--text",
        "Hello, world!",
    )
    assert encode_result.returncode == 0
    ids = json.loads(encode_result.stdout.rstrip("\n"))

    decode_result = _run_cli(
        "decode",
        "--model",
        str(cli_trained_artifact),
        "--ids",
        *(str(i) for i in ids),
    )
    assert decode_result.returncode == 0
    assert decode_result.stderr == ""
    assert decode_result.stdout == "Hello, world!"


def test_decode_unknown_id_fails_without_stdout_leak(
    cli_trained_artifact: Path,
) -> None:
    result = _run_cli(
        "decode",
        "--model",
        str(cli_trained_artifact),
        "--ids",
        "999999",
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr != ""


def test_decode_invalid_utf8_sequence_fails_without_stdout_leak(
    cli_trained_artifact: Path,
) -> None:
    """Token id ``128`` resolves to ``b"\\x80"``, a lone UTF-8 continuation
    byte that is invalid under strict decoding regardless of merge
    training. This is the same construction the public-API test uses to
    prove ``UnicodeDecodeError`` is surfaced on the decoder path; here
    we prove the CLI translates that exception into a stderr-only,
    non-zero exit.
    """
    result = _run_cli(
        "decode",
        "--model",
        str(cli_trained_artifact),
        "--ids",
        "128",
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr != ""


def test_encode_missing_model_fails_without_stdout_leak(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.json"
    result = _run_cli(
        "encode",
        "--model",
        str(missing),
        "--text",
        "Hello",
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr != ""
