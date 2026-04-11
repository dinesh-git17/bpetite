"""Unit tests for the canonical GPT-2-style pre-tokenizer.

Covers PRD FR-4 (exact pattern), FR-5 (source order and byte preservation),
and FR-6 (no normalization, case folding, prefix-space insertion, or
whitespace trimming). The tests import directly from the internal
``bpetite._pretokenizer`` module per the pytest conventions for Phase 2
tests — the public ``Tokenizer`` API does not exist yet and would not add
coverage over the internal function.
"""

import pytest

from bpetite._pretokenizer import pretokenize

ROUNDTRIP_CASES: list[tuple[str, str]] = [
    ("empty string", ""),
    ("single space", " "),
    ("tab and newline", "\t\n"),
    ("ascii lowercase", "hello world"),
    ("ascii mixed case", "Hello WORLD"),
    ("ascii sentence", "the quick brown fox jumps over the lazy dog"),
    ("trailing whitespace", "spaces   "),
    ("leading whitespace", "   spaces"),
    ("double newline", "line1\n\nline2"),
    ("digits", "123 456 7890"),
    ("punctuation run", "!!! ??? ..."),
    ("mixed punctuation", "wait -- what?!"),
    ("contraction s", "it's"),
    ("contraction t", "don't"),
    ("contraction ll", "I'll"),
    ("contraction ve", "we've"),
    ("contraction re", "they're"),
    ("contraction d", "she'd"),
    ("contraction m", "I'm"),
    ("contractions chained", "I've don't we're she'd"),
    ("emoji single", "\U0001f600"),
    ("emoji with text", "hello \U0001f389 world"),
    ("cjk", "\u4f60\u597d\u4e16\u754c"),
    ("cjk with ascii", "hello \u4f60\u597d world"),
    (
        "arabic",
        "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645",
    ),
    ("mixed scripts", "a\u4f60\u0645\U0001f600 mixed"),
    ("endoftext literal", "<|endoftext|>"),
    ("endoftext with text", "prefix <|endoftext|> suffix"),
    ("unicode whitespace", "hello\u00a0\u3000world"),
    ("ideographic spaces only", "\u3000\u3000\u3000"),
]


@pytest.mark.parametrize(("label", "text"), ROUNDTRIP_CASES)
def test_pretokenize_roundtrip_bytes(label: str, text: str) -> None:
    """FR-5: concatenating chunks reproduces the UTF-8 encoding exactly."""
    assert b"".join(pretokenize(text)) == text.encode("utf-8")


@pytest.mark.parametrize(("label", "text"), ROUNDTRIP_CASES)
def test_pretokenize_chunks_are_strict_bytes(label: str, text: str) -> None:
    """Every chunk is a ``bytes`` instance — no bytearray, memoryview, or str."""
    for chunk in pretokenize(text):
        assert isinstance(chunk, bytes)


def test_pretokenize_empty_returns_empty_list() -> None:
    """``pretokenize('')`` is ``[]`` (not ``None``, not ``[b'']``)."""
    assert pretokenize("") == []


@pytest.mark.parametrize(
    ("text", "expected_substring"),
    [
        ("Hello", b"Hello"),
        ("WORLD", b"WORLD"),
        ("MixED CaSE", b"MixED"),
        ("MixED CaSE", b"CaSE"),
    ],
)
def test_pretokenize_preserves_case(text: str, expected_substring: bytes) -> None:
    """FR-6: no case folding — the exact case bytes survive concatenation."""
    joined = b"".join(pretokenize(text))
    assert expected_substring in joined


@pytest.mark.parametrize(
    "text",
    [
        "   leading",
        "trailing   ",
        "   both   ",
        "\n\nleading newlines",
        "trailing newlines\n\n",
        "\t\t\ttabs",
    ],
)
def test_pretokenize_no_whitespace_trimming(text: str) -> None:
    """FR-6: no leading/trailing whitespace is dropped; byte length is preserved."""
    joined = b"".join(pretokenize(text))
    assert joined == text.encode("utf-8")
    assert len(joined) == len(text.encode("utf-8"))


@pytest.mark.parametrize(
    ("text", "required_chunk"),
    [
        ("it's", b"'s"),
        ("don't", b"'t"),
        ("I'll", b"'ll"),
        ("we've", b"'ve"),
        ("they're", b"'re"),
        ("she'd", b"'d"),
        ("I'm", b"'m"),
    ],
)
def test_pretokenize_splits_contractions(text: str, required_chunk: bytes) -> None:
    """FR-4: the contraction alternative in the pattern isolates suffixes."""
    chunks = pretokenize(text)
    assert required_chunk in chunks


def test_pretokenize_preserves_source_order() -> None:
    """FR-5: chunks appear in input order (not sorted, not deduplicated)."""
    text = "alpha beta gamma alpha"
    chunks = pretokenize(text)
    positions = [b"alpha", b" beta", b" gamma", b" alpha"]
    assert chunks == positions


def test_pretokenize_does_not_insert_prefix_space() -> None:
    """FR-6: a leading word must not gain a prefix space from the pre-tokenizer."""
    chunks = pretokenize("hello world")
    assert chunks[0] == b"hello"
    assert not chunks[0].startswith(b" ")


def test_pretokenize_tiny_corpus_roundtrip(tiny_corpus: str) -> None:
    """The shared tiny corpus fixture roundtrips byte-identically (FR-5)."""
    assert b"".join(pretokenize(tiny_corpus)) == tiny_corpus.encode("utf-8")


def test_pretokenize_unicode_corpus_roundtrip(unicode_corpus: str) -> None:
    """The multi-script Unicode corpus fixture roundtrips byte-identically (FR-5)."""
    assert b"".join(pretokenize(unicode_corpus)) == unicode_corpus.encode("utf-8")


def test_pretokenize_empty_corpus_is_empty(empty_corpus: str) -> None:
    """The empty corpus fixture produces no chunks."""
    assert pretokenize(empty_corpus) == []
