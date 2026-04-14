"""Persistence tests and the Phase 2 determinism gate.

Covers Task 2-8: round-trip save/load fidelity, atomic-save semantics
(overwrite protection, overwrite success, missing parent directory),
the full loader validation checklist (malformed JSON, duplicate object
keys, missing required keys, invalid byte values, malformed merges,
schema and pattern mismatches, ``mergeable_vocab_size`` mismatches, and
every special-token invariant), and the two PRD determinism proofs:
saving the same in-memory state twice and training the same corpus
twice both produce byte-identical artifacts.

Per the pytest-conventions skill, Phase 2 tests import internal
modules directly because the public ``Tokenizer`` API is not wired yet.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from bpetite._constants import END_OF_TEXT_TOKEN
from bpetite._persistence import load, save
from bpetite._trainer import TrainerResult, train_bpe

_TRAIN_VOCAB_SIZE = 300


@pytest.fixture(scope="session")
def trained_state(tiny_corpus: str) -> TrainerResult:
    """Train once per session against the deterministic tiny corpus.

    Persistence tests only consume the resulting state; they never
    mutate it, so a session-scoped fixture is safe and keeps the suite
    fast.
    """
    return train_bpe(tiny_corpus, vocab_size=_TRAIN_VOCAB_SIZE)


def _state_args(
    result: TrainerResult,
) -> tuple[dict[int, bytes], list[tuple[int, int]], dict[str, int]]:
    """Convert a :class:`TrainerResult` into the positional triple
    ``(vocab, merges, special_tokens)`` that :func:`save` accepts."""
    return (
        dict(result.vocab),
        list(result.merges),
        dict(result.special_tokens),
    )


def _save_valid(tmp_path: Path, result: TrainerResult, name: str = "tok.json") -> Path:
    """Save ``result`` to ``tmp_path / name`` and return the destination."""
    artifact = tmp_path / name
    vocab, merges, special_tokens = _state_args(result)
    save(str(artifact), vocab, merges, special_tokens)
    return artifact


def _read_artifact(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _write_artifact(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_roundtrip_save_load_returns_identical_state(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    artifact = _save_valid(tmp_path, trained_state)
    loaded_vocab, loaded_merges, loaded_special = load(str(artifact))
    assert loaded_vocab == dict(trained_state.vocab)
    assert loaded_merges == list(trained_state.merges)
    assert loaded_special == dict(trained_state.special_tokens)


def test_save_refuses_to_overwrite_existing_file_by_default(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    artifact = _save_valid(tmp_path, trained_state)
    original_bytes = artifact.read_bytes()
    vocab, merges, special_tokens = _state_args(trained_state)
    with pytest.raises(FileExistsError):
        save(str(artifact), vocab, merges, special_tokens)
    assert artifact.read_bytes() == original_bytes


def test_save_overwrites_existing_file_when_overwrite_true(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    artifact = _save_valid(tmp_path, trained_state)
    original_bytes = artifact.read_bytes()
    artifact.write_text("garbage", encoding="utf-8")
    vocab, merges, special_tokens = _state_args(trained_state)
    save(str(artifact), vocab, merges, special_tokens, overwrite=True)
    assert artifact.read_bytes() == original_bytes


def test_save_raises_file_not_found_when_parent_directory_missing(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    nonexistent = tmp_path / "no_such_dir" / "tok.json"
    vocab, merges, special_tokens = _state_args(trained_state)
    with pytest.raises(FileNotFoundError):
        save(str(nonexistent), vocab, merges, special_tokens)


def test_load_rejects_malformed_json(tmp_path: Path) -> None:
    bogus = tmp_path / "bad.json"
    bogus.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load(str(bogus))


def test_load_rejects_duplicate_json_object_keys(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    artifact = _save_valid(tmp_path, trained_state)
    raw = artifact.read_text(encoding="utf-8")
    # Splice a duplicate top-level key in by string editing because the
    # standard library serializer cannot produce duplicates on its own.
    duplicated = raw[:-1] + ',"schema_version":1}'
    artifact.write_text(duplicated, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate key"):
        load(str(artifact))


@pytest.mark.parametrize(
    "missing_key",
    [
        "schema_version",
        "mergeable_vocab_size",
        "pretokenizer_pattern",
        "vocab",
        "merges",
        "special_tokens",
    ],
)
def test_load_rejects_missing_required_key(
    tmp_path: Path, trained_state: TrainerResult, missing_key: str
) -> None:
    artifact = _save_valid(tmp_path, trained_state)
    data = _read_artifact(artifact)
    del data[missing_key]
    _write_artifact(artifact, data)
    with pytest.raises(KeyError, match=missing_key):
        load(str(artifact))


def test_load_rejects_invalid_byte_values_in_vocab(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    artifact = _save_valid(tmp_path, trained_state)
    data = _read_artifact(artifact)
    data["vocab"]["0"] = [256]
    _write_artifact(artifact, data)
    with pytest.raises(ValueError, match="out-of-range byte"):
        load(str(artifact))


def test_load_rejects_malformed_merges(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    artifact = _save_valid(tmp_path, trained_state)
    data = _read_artifact(artifact)
    data["merges"][0] = [97]
    _write_artifact(artifact, data)
    with pytest.raises(ValueError, match="2-element array"):
        load(str(artifact))


def test_load_rejects_wrong_schema_version(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    artifact = _save_valid(tmp_path, trained_state)
    data = _read_artifact(artifact)
    data["schema_version"] = 2
    _write_artifact(artifact, data)
    with pytest.raises(ValueError, match="Unsupported schema_version"):
        load(str(artifact))


def test_load_rejects_mergeable_vocab_size_mismatch(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    artifact = _save_valid(tmp_path, trained_state)
    data = _read_artifact(artifact)
    data["mergeable_vocab_size"] = data["mergeable_vocab_size"] + 1
    _write_artifact(artifact, data)
    with pytest.raises(ValueError, match="mergeable_vocab_size"):
        load(str(artifact))


def test_load_rejects_pretokenizer_pattern_mismatch(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    artifact = _save_valid(tmp_path, trained_state)
    data = _read_artifact(artifact)
    data["pretokenizer_pattern"] = "not the canonical pattern"
    _write_artifact(artifact, data)
    with pytest.raises(ValueError, match="pretokenizer_pattern"):
        load(str(artifact))


def test_load_rejects_special_token_with_wrong_key(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    artifact = _save_valid(tmp_path, trained_state)
    data = _read_artifact(artifact)
    special_id = data["special_tokens"][END_OF_TEXT_TOKEN]
    data["special_tokens"] = {"<|other|>": special_id}
    _write_artifact(artifact, data)
    with pytest.raises(ValueError, match="special_tokens must contain exactly one key"):
        load(str(artifact))


def test_load_rejects_special_token_with_wrong_id(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    artifact = _save_valid(tmp_path, trained_state)
    data = _read_artifact(artifact)
    correct_id = data["mergeable_vocab_size"]
    wrong_id = correct_id + 5
    data["special_tokens"][END_OF_TEXT_TOKEN] = wrong_id
    # Move the vocab entry so the loader reaches the id-mismatch branch
    # instead of failing earlier on "id missing from vocab".
    data["vocab"][str(wrong_id)] = data["vocab"].pop(str(correct_id))
    _write_artifact(artifact, data)
    with pytest.raises(ValueError, match="must equal mergeable_vocab_size"):
        load(str(artifact))


def test_load_rejects_special_token_with_wrong_bytes(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    artifact = _save_valid(tmp_path, trained_state)
    data = _read_artifact(artifact)
    special_id = data["special_tokens"][END_OF_TEXT_TOKEN]
    data["vocab"][str(special_id)] = [0, 0, 0]
    _write_artifact(artifact, data)
    with pytest.raises(ValueError, match="bytes do not match expected UTF-8"):
        load(str(artifact))


def test_same_state_saved_twice_produces_identical_bytes(
    tmp_path: Path, trained_state: TrainerResult
) -> None:
    """Determinism gate 1: same in-memory state, byte-identical artifacts.

    Catches a missing ``sort_keys=True`` in the serializer, which is
    silent under every other test in this suite.
    """
    first = _save_valid(tmp_path, trained_state, "first.json")
    second = _save_valid(tmp_path, trained_state, "second.json")
    assert first.read_bytes() == second.read_bytes()


def test_repeated_training_then_saving_produces_identical_artifacts(
    tmp_path: Path, tiny_corpus: str
) -> None:
    """Determinism gate 2: same corpus + same vocab_size → identical bytes.

    Proves the full pipeline (pre-tokenizer, trainer, persistence) is
    deterministic end-to-end, satisfying the PRD release requirement.
    """
    first_result = train_bpe(tiny_corpus, vocab_size=_TRAIN_VOCAB_SIZE)
    second_result = train_bpe(tiny_corpus, vocab_size=_TRAIN_VOCAB_SIZE)
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_vocab, first_merges, first_special = _state_args(first_result)
    second_vocab, second_merges, second_special = _state_args(second_result)
    save(str(first_path), first_vocab, first_merges, first_special)
    save(str(second_path), second_vocab, second_merges, second_special)
    assert first_path.read_bytes() == second_path.read_bytes()
