---
name: artifact-schema
description: "Reference skill for the bpetite persistence layer: JSON artifact schema, atomic save implementation, and full loader validation checklist. Auto-invoke whenever working on _persistence.py or test_persistence.py. Trigger on any of: save, load, artifact, persistence, schema_version, JSON schema, atomic write, overwrite, vocab keys, merge shape, token ID uniqueness, NamedTemporaryFile, os.replace, or sort_keys. This skill exists because the persistence layer has several load-bearing mechanical rules that are silent failure modes when missed — especially sort_keys=True (determinism killer), wrong temp-file directory (breaks atomic replace on some filesystems), and incomplete loader validation (passes in unit tests, fails in edge cases). Do not implement or review _persistence.py without loading this skill first."
---

# bpetite Artifact Schema — Persistence Reference

This skill is the authoritative reference for the `bpetite` persistence
layer. Read it completely before writing or reviewing any code in
`_persistence.py` or `test_persistence.py`.

---

## 1. Artifact Schema v1 — Field Specification

The saved artifact is a single JSON file. Every field below is required.
Missing fields must cause `KeyError` at load time, not silent defaults.

```json
{
  "schema_version": 1,
  "mergeable_vocab_size": 512,
  "pretokenizer_pattern": "'(?:[sdmt]|ll|ve|re)| ?\\p{L}+| ?\\p{N}+| ?[^\\s\\p{L}\\p{N}]+|\\s+(?!\\S)|\\s+",
  "vocab": {
    "0": [0],
    "1": [1],
    "255": [255],
    "256": [116, 104, 101],
    "512": [60, 124, 101, 110, 100, 111, 102, 116, 101, 120, 116, 124, 62]
  },
  "merges": [
    [116, 104],
    [256, 101]
  ],
  "special_tokens": {
    "<|endoftext|>": 512
  }
}
```

### Field-by-field rules

| Field                  | Type     | Rule                                                                                                                                              |
| ---------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | ------------------------------------------- |
| `schema_version`       | `int`    | Must equal `1`. Any other value → `ValueError`.                                                                                                   |
| `mergeable_vocab_size` | `int`    | Must equal `len(merges) + 256`.                                                                                                                   |
| `pretokenizer_pattern` | `str`    | Must exactly match `_constants.PRETOKENIZER_PATTERN`. Any deviation → `ValueError`.                                                               |
| `vocab`                | `object` | Keys are **decimal strings** (never integers — JSON keys cannot be integers). Values are **lists of integers**, each in range `0..255` inclusive. |
| `merges`               | `array`  | Each entry is an array of **exactly 2 integers**. Order encodes merge rank: index 0 = rank 0.                                                     |
| `special_tokens`       | `object` | Must be exactly `{"<                                                                                                                              | endoftext | >": <id>}`. No other keys. No missing keys. |

---

## 2. Vocab Key and Value Rules (Critical)

**Keys are always decimal strings.** JSON object keys are always strings.
The saver must convert integer IDs to strings. The loader must convert
string keys to integers.

```python
# CORRECT: save
"vocab": {str(k): list(v) for k, v in vocab.items()}

# CORRECT: load
vocab = {int(k): bytes(v) for k, v in raw["vocab"].items()}

# WRONG: do not use integer keys in JSON serialization
# json.dumps({"vocab": {256: [116, 104, 101]}}) → raises TypeError in stdlib json
```

**Values are lists of integers in `0..255`.** The saver converts `bytes`
to `list[int]`. The loader converts `list[int]` back to `bytes`. Byte
range must be validated on load.

```python
# CORRECT: save
bytes_value → list(bytes_value)   # bytes [116, 104, 101] → [116, 104, 101]

# CORRECT: load + validate
for raw_bytes in raw_vocab_value:
    if not isinstance(raw_bytes, int) or not (0 <= raw_bytes <= 255):
        raise ValueError(f"Invalid byte value: {raw_bytes!r}")
```

**Special-token vocab entry.** The special token `<|endoftext|>` must
appear in vocab with its ID and its bytes must be the UTF-8 encoding of
the literal string.

```python
# CORRECT: building vocab before save
special_id = mergeable_vocab_size  # first ID >= mergeable_vocab_size
vocab[special_id] = SPECIAL_TOKEN.encode("utf-8")
# "<|endoftext|>".encode("utf-8") == b'<|endoftext|>'
```

---

## 3. Sort Keys — Mandatory for Determinism

**`sort_keys=True` is a release requirement, not a style preference.**
Without it, Python dicts serialize in insertion order, which is
implementation-defined and can vary across runs for the `vocab` object
(which has integer keys stored in a dict). Two saves of the same
in-memory state can produce different bytes if `sort_keys` is omitted.

This is the exact class of silent bug that only surfaces in the
determinism test (`test_persistence.py::test_same_tokenizer_saved_twice_is_identical`).
It will not surface in any other test.

```python
# CORRECT — determinism-safe
json.dumps(artifact, sort_keys=True, separators=(",", ":"))

# WRONG — fails determinism test silently
json.dumps(artifact)
json.dumps(artifact, indent=2)
json.dumps(artifact, separators=(",", ":"))  # still wrong: no sort_keys
```

The `separators=(",", ":")` removes all whitespace for compact output.
Both `sort_keys=True` and `separators=(",", ":")` are required together.

---

## 4. Atomic Write — Correct Pattern

**The temp file must be created in the same directory as the destination.**
`os.replace` is atomic only when source and destination are on the same
filesystem. Placing the temp file in `/tmp/` or the system default temp
directory will silently produce a non-atomic cross-device rename on some
configurations (e.g., when the project directory is a different mount point).

```python
import json
import os
import tempfile
from pathlib import Path

def save(
    path: str,
    vocab: dict[int, bytes],
    merges: list[tuple[int, int]],
    special_tokens: dict[str, int],
    overwrite: bool = False,
) -> None:
    dest = Path(path)

    # Fail fast: missing parent directory
    if not dest.parent.exists():
        raise FileNotFoundError(f"Parent directory does not exist: {dest.parent}")

    # Fail fast: overwrite protection
    if dest.exists() and not overwrite:
        raise FileExistsError(f"File already exists (use overwrite=True): {dest}")

    artifact = _build_artifact(vocab, merges, special_tokens)
    payload = json.dumps(artifact, sort_keys=True, separators=(",", ":"))

    # Atomic write: temp file in same directory as dest
    fd, tmp_path = tempfile.mkstemp(dir=dest.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, dest)   # atomic on POSIX; best-effort on Windows
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
```

**Why `tempfile.mkstemp(dir=dest.parent)`:** This is the only pattern that
is both atomic and correct. `NamedTemporaryFile` is an acceptable
alternative but requires `delete=False` and explicit `os.replace` after
closing. `mkstemp` is simpler and clearer.

**Cleanup on failure:** Always attempt to remove the temp file if
`os.replace` fails, but do not suppress the original exception.

---

## 5. Loader Validation Checklist

Run these checks in this order. Each failure raises a typed exception with
a grep-friendly message.

```python
def load(path: str) -> tuple[dict[int, bytes], list[tuple[int, int]], dict[str, int]]:
    raw_text = Path(path).read_text(encoding="utf-8")

    # 1. Valid JSON syntax
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Artifact is not valid JSON: {e}") from e

    # 2. schema_version present and correct
    if "schema_version" not in data:
        raise KeyError("Missing required key: schema_version")
    if data["schema_version"] != 1:
        raise ValueError(
            f"Unsupported schema_version: {data['schema_version']!r} (expected 1)"
        )

    # 3. All required keys present
    REQUIRED = {
        "schema_version", "mergeable_vocab_size", "pretokenizer_pattern",
        "vocab", "merges", "special_tokens",
    }
    missing = REQUIRED - data.keys()
    if missing:
        raise KeyError(f"Missing required keys: {sorted(missing)}")

    # 4. pretokenizer_pattern matches canonical constant
    if data["pretokenizer_pattern"] != PRETOKENIZER_PATTERN:
        raise ValueError(
            "pretokenizer_pattern in artifact does not match canonical pattern"
        )

    # 5. merges shape and count
    raw_merges = data["merges"]
    if not isinstance(raw_merges, list):
        raise ValueError("merges must be a JSON array")
    merges: list[tuple[int, int]] = []
    for i, entry in enumerate(raw_merges):
        if not isinstance(entry, list) or len(entry) != 2:
            raise ValueError(f"merges[{i}] must be a 2-element array")
        a, b = entry
        if not isinstance(a, int) or not isinstance(b, int):
            raise ValueError(f"merges[{i}] must contain integers")
        merges.append((a, b))

    # 6. mergeable_vocab_size consistency
    expected_mvs = len(merges) + 256
    if data["mergeable_vocab_size"] != expected_mvs:
        raise ValueError(
            f"mergeable_vocab_size {data['mergeable_vocab_size']} "
            f"does not match len(merges)+256={expected_mvs}"
        )

    # 7. vocab: keys are decimal strings, values are byte lists in 0..255,
    #    token IDs are unique
    raw_vocab = data["vocab"]
    if not isinstance(raw_vocab, dict):
        raise ValueError("vocab must be a JSON object")
    seen_ids: set[int] = set()
    vocab: dict[int, bytes] = {}
    for str_key, raw_val in raw_vocab.items():
        try:
            token_id = int(str_key)
        except ValueError:
            raise ValueError(f"vocab key is not a decimal integer string: {str_key!r}")
        if token_id in seen_ids:
            raise ValueError(f"Duplicate token ID in vocab: {token_id}")
        seen_ids.add(token_id)
        if not isinstance(raw_val, list):
            raise ValueError(f"vocab[{str_key!r}] must be a list")
        for byte_val in raw_val:
            if not isinstance(byte_val, int) or not (0 <= byte_val <= 255):
                raise ValueError(
                    f"vocab[{str_key!r}] contains invalid byte value: {byte_val!r}"
                )
        vocab[token_id] = bytes(raw_val)

    # 8. special_tokens: must be exactly {"<|endoftext|>": <id>}
    raw_st = data["special_tokens"]
    if not isinstance(raw_st, dict):
        raise ValueError("special_tokens must be a JSON object")
    if set(raw_st.keys()) != {SPECIAL_TOKEN}:
        raise ValueError(
            f"special_tokens must contain exactly one key: {SPECIAL_TOKEN!r}"
        )
    special_id = raw_st[SPECIAL_TOKEN]
    if not isinstance(special_id, int):
        raise ValueError(f"special_tokens value must be an integer, got {special_id!r}")

    # 9. special token ID is >= mergeable_vocab_size
    mvs = data["mergeable_vocab_size"]
    if special_id < mvs:
        raise ValueError(
            f"special_token ID {special_id} must be >= mergeable_vocab_size {mvs}"
        )

    # 10. special token ID is present in vocab and maps to correct bytes
    if special_id not in vocab:
        raise ValueError(
            f"special_token ID {special_id} is not present in vocab"
        )
    expected_bytes = SPECIAL_TOKEN.encode("utf-8")
    if vocab[special_id] != expected_bytes:
        raise ValueError(
            f"vocab[{special_id}] bytes do not match expected UTF-8 for "
            f"{SPECIAL_TOKEN!r}"
        )

    special_tokens: dict[str, int] = {SPECIAL_TOKEN: special_id}
    return vocab, merges, special_tokens
```

---

## 6. Duplicate JSON Key Handling

Python's `json.loads` does **not** reject duplicate keys by default. The
last value wins silently. This means a crafted artifact can smuggle
arbitrary vocabulary entries. Use a custom `object_pairs_hook` to detect
duplicates during parse.

```python
def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: set[str] = set()
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"Duplicate key in JSON object: {key!r}")
        seen.add(key)
        result[key] = value
    return result

data = json.loads(raw_text, object_pairs_hook=_reject_duplicate_keys)
```

This is tested by `test_persistence.py::test_load_rejects_duplicate_json_keys`.

---

## 7. What to Never Do

These are the exact silent failure modes this skill exists to prevent:

| Mistake                                                      | Consequence                                                                              |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------- |
| `json.dumps(artifact)` without `sort_keys=True`              | Determinism test fails; same state → different bytes                                     |
| `tempfile.mkstemp()` without `dir=dest.parent`               | Atomic replace fails on cross-device mounts                                              |
| `json.loads(raw_text)` without duplicate-key detection       | Crafted artifact with duplicate vocab keys passes validation silently                    |
| Integer keys in `vocab` dict passed directly to `json.dumps` | `TypeError` at save time (JSON keys must be strings)                                     |
| `bytes` values in `vocab` passed directly to `json.dumps`    | `TypeError` at save time (bytes are not JSON-serializable)                               |
| Loader that evaluates or imports from artifact content       | Security violation; artifact must be data-only JSON parsing                              |
| Saving without validating parent exists                      | `FileNotFoundError` is expected behavior per PRD; do not create missing parents silently |
| Swallowing the exception from `os.replace`                   | Temp file is orphaned; caller cannot retry safely                                        |

---

## 8. Test Coverage Reference

When writing `test_persistence.py`, these are the required test cases per
the PRD and task list (Task 2-8):

- Round-trip save/load: `load(save(state))` returns identical state
- Overwrite protection: saving to an existing file without `overwrite=True` → `FileExistsError`
- Overwrite success: saving with `overwrite=True` succeeds atomically
- Missing parent directory → `FileNotFoundError`
- Malformed JSON → `ValueError`
- Duplicate JSON keys → `ValueError`
- Missing required keys → `KeyError`
- Invalid byte values (outside `0..255`) → `ValueError`
- Malformed merges (not 2-element arrays) → `ValueError`
- Schema version mismatch → `ValueError`
- `mergeable_vocab_size` mismatch → `ValueError`
- Regex pattern mismatch → `ValueError`
- Special-token mismatch (wrong key, wrong ID, wrong bytes) → `ValueError`
- **Determinism gate 1**: same `(vocab, merges, special_tokens)` saved twice → identical file bytes
- **Determinism gate 2**: training same corpus twice at same `vocab_size`, saving both → identical file bytes

The determinism gates are the highest-value tests in this suite. They are
the only mechanism that catches missing `sort_keys=True` before it reaches
a reviewer.
