"""Persistence layer for bpetite tokenizer artifacts.

This module serializes a trained tokenizer to a single versioned JSON
file and reloads it with byte-for-byte fidelity. The on-disk format is
Artifact Schema v1 (see :data:`bpetite._constants.SCHEMA_VERSION`):

* top-level keys: ``schema_version``, ``mergeable_vocab_size``,
  ``pretokenizer_pattern``, ``vocab``, ``merges``, ``special_tokens``;
* ``vocab`` maps decimal-string token ids to byte lists in ``0..255``;
* ``merges`` is an ordered list of ``[left_id, right_id]`` pairs whose
  index encodes merge rank;
* ``special_tokens`` is exactly ``{"<|endoftext|>": <id>}``.

Writes are atomic: the payload is written to a temp file inside the
destination's parent directory and renamed into place with
:meth:`pathlib.Path.replace`. The temp file must live on the same
filesystem as the destination or the rename is not actually atomic,
so the temp directory is pinned to ``dest.parent`` on purpose.

Reads are strict: every field shape, every byte range, and the
special-token invariant are validated before returning. Duplicate JSON
object keys are rejected at parse time via ``object_pairs_hook``
because ``json.loads`` would otherwise keep the last value silently
and let a crafted artifact smuggle vocab entries past validation.

Determinism is load-bearing. Serialization uses ``sort_keys=True`` and
compact separators so that the same in-memory tokenizer state always
produces identical file bytes. This is the invariant the Phase 2
determinism gate tests against.

See ``docs/phase-2/persistence.md`` for the full schema walkthrough,
loader validation checklist, and failure-mode table.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from bpetite._constants import (
    END_OF_TEXT_TOKEN,
    PRETOKENIZER_PATTERN,
    SCHEMA_VERSION,
)

_BASE_VOCAB_SIZE = 256

_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "mergeable_vocab_size",
        "pretokenizer_pattern",
        "vocab",
        "merges",
        "special_tokens",
    }
)


def save(
    path: str,
    vocab: dict[int, bytes],
    merges: list[tuple[int, int]],
    special_tokens: dict[str, int],
    overwrite: bool = False,
) -> None:
    """Write a tokenizer artifact atomically to ``path``.

    The JSON payload follows Artifact Schema v1. Serialization is
    deterministic: keys are sorted and separators are compact so that
    the same in-memory state always produces identical bytes on disk.
    The write goes through a temp file in ``path``'s parent directory
    and is swapped into place with an atomic rename.

    Args:
        path: Destination file path. Must have an existing parent
            directory.
        vocab: Full token-id to canonical-bytes mapping, including the
            reserved special-token entry that the trainer places past
            the mergeable range.
        merges: Ordered merge list. The index of each entry encodes
            its merge rank: rank ``0`` corresponds to token id ``256``.
        special_tokens: Exactly ``{"<|endoftext|>": <id>}``, where
            ``<id>`` is the first integer id greater than or equal to
            ``len(merges) + 256``.
        overwrite: If ``False`` and ``path`` already exists, the save
            fails with :class:`FileExistsError`. If ``True``, the
            existing file is atomically replaced.

    Raises:
        FileNotFoundError: If the parent directory of ``path`` does
            not exist.
        FileExistsError: If ``path`` already exists and ``overwrite``
            is ``False``.
    """
    dest = Path(path)

    if not dest.parent.exists():
        msg = f"Parent directory does not exist: {dest.parent}"
        raise FileNotFoundError(msg)

    if dest.exists() and not overwrite:
        msg = f"File already exists (use overwrite=True): {dest}"
        raise FileExistsError(msg)

    artifact = _build_artifact(vocab, merges, special_tokens)
    # sort_keys=True + compact separators make save byte-deterministic.
    payload = json.dumps(artifact, sort_keys=True, separators=(",", ":"))

    # Temp file must share a filesystem with dest so replace() is atomic.
    fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(payload)
        tmp_path.replace(dest)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def load(
    path: str,
) -> tuple[dict[int, bytes], list[tuple[int, int]], dict[str, int]]:
    """Load and validate a tokenizer artifact from ``path``.

    Parses the file as JSON with duplicate object keys rejected at
    parse time, then walks the full validation checklist for Schema
    v1 before reconstructing the in-memory tokenizer state.

    Args:
        path: Path to a Schema v1 artifact file.

    Returns:
        A ``(vocab, merges, special_tokens)`` triple reconstructed
        from the artifact. The shape matches what :func:`save`
        accepts so a round-trip is a straightforward call pair.

    Raises:
        KeyError: If required top-level keys are missing.
        ValueError: If the file is not valid JSON, contains duplicate
            object keys, has the wrong ``schema_version`` or
            ``pretokenizer_pattern``, violates
            ``mergeable_vocab_size == len(merges) + 256``, has
            malformed vocab or merge shapes, contains byte values
            outside ``0..255``, fails any special-token invariant,
            or is not valid UTF-8.
    """
    try:
        raw_text = Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        msg = f"Artifact is not valid UTF-8: {exc}"
        raise ValueError(msg) from exc

    try:
        data = json.loads(
            raw_text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constants,
        )
    except json.JSONDecodeError as exc:
        msg = f"Artifact is not valid JSON: {exc}"
        raise ValueError(msg) from exc

    if not isinstance(data, dict):
        msg = "Artifact top-level value must be a JSON object"
        raise ValueError(msg)

    if "schema_version" not in data:
        msg = "Missing required key: schema_version"
        raise KeyError(msg)
    schema_version = data["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        msg = f"schema_version must be an integer, got {schema_version!r}"
        raise ValueError(msg)
    if schema_version != SCHEMA_VERSION:
        msg = (
            f"Unsupported schema_version: {schema_version!r} "
            f"(expected {SCHEMA_VERSION})"
        )
        raise ValueError(msg)

    missing = _REQUIRED_KEYS - data.keys()
    if missing:
        msg = f"Missing required keys: {sorted(missing)}"
        raise KeyError(msg)
    unexpected = data.keys() - _REQUIRED_KEYS
    if unexpected:
        msg = f"Artifact contains unexpected top-level keys: {sorted(unexpected)}"
        raise ValueError(msg)

    pattern = data["pretokenizer_pattern"]
    if not isinstance(pattern, str):
        msg = f"pretokenizer_pattern must be a string, got {pattern!r}"
        raise ValueError(msg)
    if pattern != PRETOKENIZER_PATTERN:
        msg = "pretokenizer_pattern in artifact does not match canonical pattern"
        raise ValueError(msg)

    merges = _parse_merges(data["merges"])

    declared_mvs = data["mergeable_vocab_size"]
    if isinstance(declared_mvs, bool) or not isinstance(declared_mvs, int):
        msg = f"mergeable_vocab_size must be an integer, got {declared_mvs!r}"
        raise ValueError(msg)
    expected_mvs = len(merges) + _BASE_VOCAB_SIZE
    if declared_mvs != expected_mvs:
        msg = (
            f"mergeable_vocab_size {declared_mvs} does not match "
            f"len(merges)+{_BASE_VOCAB_SIZE}={expected_mvs}"
        )
        raise ValueError(msg)

    vocab = _parse_vocab(data["vocab"])

    missing_ids = sorted(set(range(expected_mvs)) - vocab.keys())
    if missing_ids:
        preview = missing_ids[:5]
        suffix = f" (and {len(missing_ids) - 5} more)" if len(missing_ids) > 5 else ""
        msg = f"vocab is missing required token IDs: {preview}{suffix}"
        raise ValueError(msg)

    _validate_base_byte_vocab(vocab)
    _validate_merge_derived_vocab(vocab, merges)

    special_tokens = _parse_special_tokens(data["special_tokens"], declared_mvs, vocab)

    allowed_ids = set(range(expected_mvs + 1))
    extra_ids = sorted(vocab.keys() - allowed_ids)
    if extra_ids:
        preview = extra_ids[:5]
        suffix = f" (and {len(extra_ids) - 5} more)" if len(extra_ids) > 5 else ""
        msg = f"vocab contains unexpected token IDs: {preview}{suffix}"
        raise ValueError(msg)

    return vocab, merges, special_tokens


def _build_artifact(
    vocab: dict[int, bytes],
    merges: list[tuple[int, int]],
    special_tokens: dict[str, int],
) -> dict[str, Any]:
    """Translate in-memory tokenizer state into the JSON-shaped artifact.

    ``mergeable_vocab_size`` is recomputed from ``merges`` so that the
    on-disk value cannot drift from the merge list it describes.
    """
    mergeable_vocab_size = len(merges) + _BASE_VOCAB_SIZE
    return {
        "schema_version": SCHEMA_VERSION,
        "mergeable_vocab_size": mergeable_vocab_size,
        "pretokenizer_pattern": PRETOKENIZER_PATTERN,
        "vocab": {
            str(token_id): list(token_bytes) for token_id, token_bytes in vocab.items()
        },
        "merges": [[left, right] for left, right in merges],
        "special_tokens": dict(special_tokens),
    }


def _reject_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    """JSON ``object_pairs_hook`` that rejects duplicate object keys.

    Python's ``json`` module silently keeps the last value for
    duplicate keys. A crafted artifact could use that to smuggle
    vocabulary entries past validation, so fail loudly instead.
    """
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            msg = f"Duplicate key in JSON object: {key!r}"
            raise ValueError(msg)
        result[key] = value
    return result


def _reject_nonstandard_constants(constant: str) -> Any:
    """JSON ``parse_constant`` hook that rejects ``NaN``/``Infinity``.

    Python's ``json.loads`` accepts ``NaN``, ``Infinity``, and
    ``-Infinity`` by default, none of which are valid per RFC 8259.
    A crafted artifact could plant those tokens inside an unknown
    key to stay silent through the required-key check, so fail at
    parse time instead.
    """
    msg = f"Artifact contains non-standard JSON constant: {constant}"
    raise ValueError(msg)


def _parse_merges(raw_merges: Any) -> list[tuple[int, int]]:
    """Validate the raw ``merges`` field and return typed merge pairs."""
    if not isinstance(raw_merges, list):
        msg = "merges must be a JSON array"
        raise ValueError(msg)
    merges: list[tuple[int, int]] = []
    for index, entry in enumerate(raw_merges):
        if not isinstance(entry, list) or len(entry) != 2:
            msg = f"merges[{index}] must be a 2-element array"
            raise ValueError(msg)
        left, right = entry
        if isinstance(left, bool) or not isinstance(left, int):
            msg = f"merges[{index}][0] must be an integer, got {left!r}"
            raise ValueError(msg)
        if isinstance(right, bool) or not isinstance(right, int):
            msg = f"merges[{index}][1] must be an integer, got {right!r}"
            raise ValueError(msg)
        if left < 0:
            msg = f"merges[{index}][0] must be a non-negative token ID, got {left}"
            raise ValueError(msg)
        if right < 0:
            msg = f"merges[{index}][1] must be a non-negative token ID, got {right}"
            raise ValueError(msg)
        merges.append((left, right))
    return merges


def _parse_vocab(raw_vocab: Any) -> dict[int, bytes]:
    """Validate the raw ``vocab`` field and return a typed id-to-bytes map.

    JSON object keys are always strings, so the saver stringifies
    integer ids and the loader parses them back. Keys that are not
    canonical decimal integer strings (leading zeros, surrounding
    whitespace, signs, non-digits) are rejected because round-tripping
    them would silently change their textual form.
    """
    if not isinstance(raw_vocab, dict):
        msg = "vocab must be a JSON object"
        raise ValueError(msg)

    vocab: dict[int, bytes] = {}
    for raw_key, raw_value in raw_vocab.items():
        if not isinstance(raw_key, str):
            msg = f"vocab key must be a decimal integer string, got {raw_key!r}"
            raise ValueError(msg)
        try:
            token_id = int(raw_key)
        except ValueError as exc:
            msg = f"vocab key is not a decimal integer string: {raw_key!r}"
            raise ValueError(msg) from exc
        if str(token_id) != raw_key:
            msg = f"vocab key is not a canonical decimal integer string: {raw_key!r}"
            raise ValueError(msg)
        if token_id < 0:
            msg = f"vocab key must be a non-negative token ID, got {token_id}"
            raise ValueError(msg)
        if token_id in vocab:
            msg = f"Duplicate token ID in vocab: {token_id}"
            raise ValueError(msg)
        if not isinstance(raw_value, list):
            msg = f"vocab[{raw_key!r}] must be a list"
            raise ValueError(msg)

        byte_buffer = bytearray()
        for byte_val in raw_value:
            if isinstance(byte_val, bool) or not isinstance(byte_val, int):
                msg = f"vocab[{raw_key!r}] contains non-integer value: {byte_val!r}"
                raise ValueError(msg)
            if not 0 <= byte_val <= 255:
                msg = (
                    f"vocab[{raw_key!r}] contains out-of-range byte value: {byte_val!r}"
                )
                raise ValueError(msg)
            byte_buffer.append(byte_val)
        vocab[token_id] = bytes(byte_buffer)

    return vocab


def _validate_base_byte_vocab(vocab: dict[int, bytes]) -> None:
    """Enforce ``vocab[i] == bytes([i])`` for every base-byte id.

    FR-8 fixes the base vocabulary as one token per byte value. A
    corrupt artifact that remaps ``vocab[0]`` to something other than
    ``b"\\x00"`` would load into a tokenizer that decodes byte ``0``
    as the wrong character, so fail fast at load time.
    """
    for byte_id in range(_BASE_VOCAB_SIZE):
        expected = bytes([byte_id])
        if vocab[byte_id] != expected:
            msg = (
                f"vocab[{byte_id}] must be the canonical base byte "
                f"{expected!r}, got {vocab[byte_id]!r}"
            )
            raise ValueError(msg)


def _validate_merge_derived_vocab(
    vocab: dict[int, bytes],
    merges: list[tuple[int, int]],
) -> None:
    """Enforce that each merge-derived entry is its pair's concatenation.

    For merge rank ``r``, the new token id is ``256 + r`` and its
    stored bytes must equal ``vocab[left] + vocab[right]``. Each
    merge element must also reference a strictly earlier id so that
    the concatenation is unambiguous and cannot be self-referential
    or forward-pointing. The checks run in rank order, so by the
    time we look at rank ``r``, every referenced id is already
    validated.
    """
    for rank, (left, right) in enumerate(merges):
        new_id = _BASE_VOCAB_SIZE + rank
        if left >= new_id or right >= new_id:
            msg = (
                f"merges[{rank}] = ({left}, {right}) must reference token "
                f"ids strictly less than {new_id} (the merge's own id)"
            )
            raise ValueError(msg)
        expected = vocab[left] + vocab[right]
        if vocab[new_id] != expected:
            msg = (
                f"vocab[{new_id}] must equal vocab[{left}] + vocab[{right}] "
                f"= {expected!r}, got {vocab[new_id]!r}"
            )
            raise ValueError(msg)


def _parse_special_tokens(
    raw: Any,
    mergeable_vocab_size: int,
    vocab: dict[int, bytes],
) -> dict[str, int]:
    """Validate ``special_tokens`` and cross-check against ``vocab``.

    Enforces the v1 invariants: exactly one special token, whose id
    lives at or past the mergeable range, whose id is present in
    ``vocab``, and whose stored bytes equal the UTF-8 encoding of the
    literal special-token string.
    """
    if not isinstance(raw, dict):
        msg = "special_tokens must be a JSON object"
        raise ValueError(msg)
    if set(raw.keys()) != {END_OF_TEXT_TOKEN}:
        msg = f"special_tokens must contain exactly one key: {END_OF_TEXT_TOKEN!r}"
        raise ValueError(msg)

    special_id = raw[END_OF_TEXT_TOKEN]
    if isinstance(special_id, bool) or not isinstance(special_id, int):
        msg = f"special_tokens value must be an integer, got {special_id!r}"
        raise ValueError(msg)

    if special_id != mergeable_vocab_size:
        msg = (
            f"special_token ID {special_id} must equal "
            f"mergeable_vocab_size {mergeable_vocab_size} "
            f"(the first id past the mergeable range)"
        )
        raise ValueError(msg)
    if special_id not in vocab:
        msg = f"special_token ID {special_id} is not present in vocab"
        raise ValueError(msg)
    expected_bytes = END_OF_TEXT_TOKEN.encode("utf-8")
    if vocab[special_id] != expected_bytes:
        msg = (
            f"vocab[{special_id}] bytes do not match expected UTF-8 "
            f"for {END_OF_TEXT_TOKEN!r}"
        )
        raise ValueError(msg)
    return {END_OF_TEXT_TOKEN: special_id}
