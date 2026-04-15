"""Public-API roundtrip and error tests for :class:`bpetite.Tokenizer`.

Covers PRD FR-17 through FR-25 via the public ``Tokenizer`` API only,
per the Phase 3 exit-gate contract: ``decode(encode(text)) == text``
holds for every required input class, the documented error cases
raise the exact exception types the PRD specifies, and save/load
preserves encode output byte-for-byte so a reloaded tokenizer is
interchangeable with its source.

Internal modules are deliberately not imported here: this file's job
is to prove the public contract, not the internals.
"""

from pathlib import Path

import pytest

from bpetite import Tokenizer

ROUNDTRIP_CASES: list[tuple[str, str]] = [
    ("empty string", ""),
    ("single space", " "),
    ("whitespace only", "   \n\t  "),
    ("ascii sentence", "Hello, world!"),
    ("emoji", "\U0001f389 party time \U0001f38a"),
    ("cjk", "\u4f60\u597d\u4e16\u754c"),
    (
        "arabic",
        "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645",
    ),
    ("mixed punctuation", "...wait\u2014what?!"),
    ("single endoftext", "<|endoftext|>"),
    (
        "multiple non-consecutive specials",
        "hello <|endoftext|> world <|endoftext|> again",
    ),
    (
        "endoftext surrounded by unicode",
        "\u524d <|endoftext|> \u5f8c",
    ),
    ("consecutive specials", "<|endoftext|><|endoftext|>"),
    ("partial special prefix", "<|endoftext"),
    ("partial special suffix", "endoftext|>"),
    ("partial special short", "<|endo"),
]


@pytest.fixture(scope="module")
def saved_and_loaded_tokenizer(
    trained_tokenizer: Tokenizer,
    tmp_path_factory: pytest.TempPathFactory,
) -> Tokenizer:
    """Persist ``trained_tokenizer`` and return a fresh loaded copy.

    Module-scoped so every save/load parity case reuses a single
    written artifact; ``tmp_path_factory`` keeps the file outside the
    repo and auto-cleans it after the session.
    """
    artifact_dir = tmp_path_factory.mktemp("roundtrip_artifact")
    artifact_path = artifact_dir / "tokenizer.json"
    trained_tokenizer.save(str(artifact_path))
    return Tokenizer.load(str(artifact_path))


@pytest.mark.parametrize(("label", "text"), ROUNDTRIP_CASES)
def test_roundtrip(trained_tokenizer: Tokenizer, label: str, text: str) -> None:
    """FR-25: ``decode(encode(text)) == text`` for every required class."""
    assert trained_tokenizer.decode(trained_tokenizer.encode(text)) == text


def test_encode_empty_returns_empty_list(trained_tokenizer: Tokenizer) -> None:
    """FR-17: ``encode("") == []``."""
    assert trained_tokenizer.encode("") == []


def test_decode_empty_returns_empty_string(trained_tokenizer: Tokenizer) -> None:
    """FR-21: ``decode([]) == ""``."""
    assert trained_tokenizer.decode([]) == ""


def test_decode_unknown_id_raises_key_error(
    trained_tokenizer: Tokenizer,
) -> None:
    """FR-22: unknown token ids raise ``KeyError``."""
    with pytest.raises(KeyError):
        trained_tokenizer.decode([999_999])


def test_decode_invalid_utf8_raises(trained_tokenizer: Tokenizer) -> None:
    """FR-23: invalid concatenated UTF-8 raises ``UnicodeDecodeError``.

    Token id ``0x80`` resolves to the single byte ``b"\\x80"``, a
    lone UTF-8 continuation byte with no preceding start byte. Strict
    UTF-8 decoding always rejects it, regardless of what merges were
    learned during training.
    """
    with pytest.raises(UnicodeDecodeError):
        trained_tokenizer.decode([0x80])


@pytest.mark.parametrize("bad_vocab_size", [-1, 0, 1, 100, 255])
def test_train_below_base_vocab_raises_value_error(
    tiny_corpus: str, bad_vocab_size: int
) -> None:
    """FR-9 boundary: ``vocab_size < 256`` raises ``ValueError``."""
    with pytest.raises(ValueError):
        Tokenizer.train(tiny_corpus, bad_vocab_size)


@pytest.mark.parametrize(("label", "text"), ROUNDTRIP_CASES)
def test_post_load_encode_parity(
    saved_and_loaded_tokenizer: Tokenizer,
    trained_tokenizer: Tokenizer,
    label: str,
    text: str,
) -> None:
    """FR-26: save/load preserves encode output byte-for-byte."""
    assert saved_and_loaded_tokenizer.encode(text) == trained_tokenizer.encode(text)


@pytest.mark.parametrize(("label", "text"), ROUNDTRIP_CASES)
def test_post_load_roundtrip(
    saved_and_loaded_tokenizer: Tokenizer, label: str, text: str
) -> None:
    """The full roundtrip invariant holds through the save/load boundary."""
    assert (
        saved_and_loaded_tokenizer.decode(saved_and_loaded_tokenizer.encode(text))
        == text
    )


def test_save_and_load_returns_tokenizer_instance(
    trained_tokenizer: Tokenizer, tmp_path: Path
) -> None:
    """Sanity: ``Tokenizer.load`` produces a ``Tokenizer``, not a dict."""
    artifact = tmp_path / "tokenizer.json"
    trained_tokenizer.save(str(artifact))
    loaded = Tokenizer.load(str(artifact))
    assert isinstance(loaded, Tokenizer)
