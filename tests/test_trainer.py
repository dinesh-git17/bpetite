"""Unit tests for the deterministic byte-level BPE trainer.

Covers PRD FR-7 through FR-15: the shared pre-tokenizer boundary contract,
256 base tokens with merge IDs starting at 256, ``vocab_size`` validation,
lexicographic tie-breaking, non-overlapping left-to-right merge application,
early-stop semantics, deterministic repeated training, and reservation of
the ``<|endoftext|>`` special token after merge training completes. Also
exercises the internal progress callback event schedule that Phase 4's CLI
will depend on.

Per the pytest-conventions skill, Phase 2 tests import the internal trainer
entry point directly because the public ``Tokenizer`` API is not wired yet
and would not add coverage over :func:`bpetite._trainer.train_bpe`.
"""

import string

import pytest

from bpetite._trainer import ProgressEvent, train_bpe

_END_OF_TEXT_BYTES = b"<|endoftext|>"
_BYTE_A = ord("a")  # 97
_BYTE_B = ord("b")  # 98


def _many_merges_corpus() -> str:
    """Return a synthetic corpus guaranteed to exceed 100 completed merges.

    All 676 two-letter ASCII words joined by spaces produce enough distinct
    adjacent byte pairs that a 250-merge training run cannot early-stop
    before the ``merge`` progress event has fired. Used only to exercise
    the ``every 100 merges`` branch of the progress callback schedule.
    """
    words = [a + b for a in string.ascii_lowercase for b in string.ascii_lowercase]
    return " ".join(words)


@pytest.mark.parametrize("bad_vocab_size", [-1, 0, 1, 100, 255])
def test_train_raises_value_error_for_vocab_size_below_256(
    bad_vocab_size: int,
) -> None:
    """FR-9: any ``vocab_size < 256`` must raise ``ValueError``."""
    with pytest.raises(ValueError, match="vocab_size"):
        train_bpe("hello world", bad_vocab_size)


def test_train_vocab_size_256_returns_base_vocab_and_zero_merges() -> None:
    """FR-8 / FR-9: ``vocab_size == 256`` yields the 256 base bytes, no
    merges, and the reserved special token at id 256."""
    result = train_bpe("hello world", 256)
    assert result.merges == ()
    assert result.mergeable_vocab_size == 256
    for byte_id in range(256):
        assert result.vocab[byte_id] == bytes([byte_id])
    assert dict(result.special_tokens) == {"<|endoftext|>": 256}
    assert result.vocab[256] == _END_OF_TEXT_BYTES


def test_train_empty_corpus_returns_no_merges_and_reserves_special_token(
    empty_corpus: str,
) -> None:
    """FR-11: an empty corpus has no pairs, so training early-stops with
    zero merges. The special token is still reserved at id 256."""
    result = train_bpe(empty_corpus, 500)
    assert result.merges == ()
    assert result.mergeable_vocab_size == 256
    assert dict(result.special_tokens) == {"<|endoftext|>": 256}
    assert result.vocab[256] == _END_OF_TEXT_BYTES


def test_train_is_deterministic_on_repeated_runs(tiny_corpus: str) -> None:
    """FR-12: identical ``(corpus, vocab_size)`` inputs produce identical
    merges, vocab, mergeable size, and special-token reservation."""
    first = train_bpe(tiny_corpus, 300)
    second = train_bpe(tiny_corpus, 300)
    assert first.merges == second.merges
    assert first.mergeable_vocab_size == second.mergeable_vocab_size
    assert dict(first.vocab) == dict(second.vocab)
    assert dict(first.special_tokens) == dict(second.special_tokens)


def test_train_merge_ids_start_at_256_and_advance_sequentially(
    tiny_corpus: str,
) -> None:
    """FR-8: merge-derived token IDs are assigned sequentially starting at
    256. For every merge at rank ``k`` the vocab entry at id ``256 + k``
    is the concatenation of its left and right child token bytes."""
    result = train_bpe(tiny_corpus, 270)
    for rank, (left, right) in enumerate(result.merges):
        merge_id = 256 + rank
        assert result.vocab[merge_id] == result.vocab[left] + result.vocab[right]


def test_train_tie_breaking_picks_lexicographically_smallest_pair() -> None:
    """FR-10: at the top count, ``min`` on standard Python tuple ordering wins.

    The test distinguishes ``min``-on-tuple from the common wrong patterns
    first-occurrence-wins (``Counter.most_common(1)``) and max-by-count
    (``max(..., key=count)``). Input ``"cab"`` is a single pre-tokenizer
    chunk whose adjacent pairs ``(99, 97)`` and ``(97, 98)`` are tied at
    frequency 1. A first-seen or max-by-count tie-breaker reaches
    ``(99, 97)`` first and stops there. Lexicographic tuple ordering
    picks ``(97, 98)`` because ``97 < 99`` on the first element.

    A corpus where the seen-order matches the lex order (for example
    ``"abcd"``) cannot distinguish these two rules and is insufficient
    for this test.
    """
    result = train_bpe("cab", 257)
    assert result.merges == ((_BYTE_A, _BYTE_B),)
    assert result.vocab[256] == b"ab"


def test_train_non_overlapping_merge_on_triple_emits_merged_then_trailing() -> None:
    """FR-10 ``[x, x, x]`` invariant: merging ``(a, a)`` on the single
    chunk ``"aaa"`` yields ``(aa, a)`` non-overlapping left-to-right and
    never ``(a, aa)``.

    Step 1 merges positions 0-1 into id 256 == ``b"aa"``, leaving the
    tail token 97 untouched. Step 2 then merges the only remaining pair
    ``(256, 97)`` into id 257 == ``b"aaa"``.
    """
    result = train_bpe("aaa", 258)
    assert result.merges == ((_BYTE_A, _BYTE_A), (256, _BYTE_A))
    assert result.vocab[256] == b"aa"
    assert result.vocab[257] == b"aaa"


def test_train_early_stops_when_no_mergeable_pairs_remain() -> None:
    """FR-11: once every chunk collapses to a single token, training stops
    even when ``vocab_size`` requests far more merges. Early-stop is not
    an error; the result reports the actual learned mergeable size."""
    result = train_bpe("aaa", 500)
    assert len(result.merges) == 2
    assert result.mergeable_vocab_size == 258
    assert dict(result.special_tokens) == {"<|endoftext|>": 258}


def test_train_early_stops_instead_of_merging_across_chunk_boundaries() -> None:
    """FR-7: pair counting is bounded by pre-tokenizer chunk boundaries.

    Corpus ``"ab\\nab\\nab\\nab\\nab"`` pre-tokenizes into the alternating
    nine-chunk stream
    ``[b"ab", b"\\n", b"ab", b"\\n", b"ab", b"\\n", b"ab", b"\\n", b"ab"]``.
    A correct trainer merges ``(97, 98)`` once; every chunk then
    collapses to a single token and training must early-stop at exactly
    one merge because no within-chunk pair remains.

    A flatten-then-count trainer instead sees the cross-boundary pair
    ``(10, 256)`` four times in the merged token stream and keeps
    merging past the correct stopping point. Asserting the exact merge
    list and the early-stop mergeable size therefore catches any
    regression that counts across chunk boundaries — including the
    subtle case where the boundary pair only appears after the first
    merge has been applied.
    """
    result = train_bpe("ab\nab\nab\nab\nab", 300)
    assert result.merges == ((_BYTE_A, _BYTE_B),)
    assert result.mergeable_vocab_size == 257


def test_train_reserves_special_token_at_first_id_past_mergeable_range(
    tiny_corpus: str,
) -> None:
    """FR-13: the special token ID equals ``mergeable_vocab_size``, and
    the vocab entry at that ID stores the UTF-8 bytes of the literal."""
    result = train_bpe(tiny_corpus, 270)
    special_id = result.mergeable_vocab_size
    assert dict(result.special_tokens) == {"<|endoftext|>": special_id}
    assert result.vocab[special_id] == _END_OF_TEXT_BYTES


def test_train_special_token_id_reflects_early_stop_mergeable_size() -> None:
    """FR-13 under early-stop: the special token ID follows the actual
    learned mergeable size, not the requested ``vocab_size``."""
    result = train_bpe("aaa", 500)
    assert result.mergeable_vocab_size == 258
    assert dict(result.special_tokens) == {"<|endoftext|>": 258}
    assert result.vocab[258] == _END_OF_TEXT_BYTES


def test_train_reserves_endoftext_as_the_only_special_token(
    tiny_corpus: str,
) -> None:
    """FR-14: ``<|endoftext|>`` is the only reserved special token in v1.
    No other literals appear in the special-token mapping."""
    result = train_bpe(tiny_corpus, 270)
    assert list(result.special_tokens.keys()) == ["<|endoftext|>"]


def test_train_treats_endoftext_literal_in_corpus_as_ordinary_text() -> None:
    """FR-15: the trainer does not extract or skip ``<|endoftext|>`` during
    pre-tokenization. A corpus containing the literal must feed its bytes
    through merge counting like any other text.

    Proof by contrast: inserting the literal into an otherwise-identical
    corpus must change the learned merge list. A trainer that special-
    cased the literal and dropped it would produce merges identical to
    the corpus without the literal.
    """
    with_literal = train_bpe("ab <|endoftext|> ab", 300)
    without_literal = train_bpe("ab ab", 300)
    assert with_literal.merges != without_literal.merges
    assert dict(with_literal.special_tokens) == {
        "<|endoftext|>": with_literal.mergeable_vocab_size
    }


def test_train_progress_callback_sub_100_merges_fires_only_start_and_complete(
    tiny_corpus: str,
) -> None:
    """Progress schedule when the run completes fewer than 100 merges.

    The full contract for a short run is: exactly one ``start`` event at
    merges_completed 0 and exactly one ``complete`` event at the final
    count, with no ``merge`` events between them. Pinning the full
    two-event sequence (rather than asserting only first/last/no-merge)
    catches a double-fired ``start`` or ``complete`` event, which a
    first-and-last-only check would miss.
    """
    events: list[ProgressEvent] = []
    result = train_bpe(tiny_corpus, 270, progress=events.append)
    assert events == [
        ProgressEvent(kind="start", merges_completed=0, merges_planned=14),
        ProgressEvent(
            kind="complete",
            merges_completed=len(result.merges),
            merges_planned=14,
        ),
    ]


def test_train_progress_callback_fires_merge_event_every_hundred_merges() -> None:
    """Progress schedule for a corpus that completes >= 200 merges.

    The full advertised contract is: one ``start`` at merges_completed 0,
    one ``merge`` event at every 100-merge tick, one ``complete`` at the
    final count. Pinning the exact event sequence (rather than asserting
    ``at least one merge event exists``) catches a bug that fires the
    100-mark event but forgets the 200-mark event, a bug that fires an
    off-count event, and a bug that omits the ``complete`` event under
    an otherwise-valid run.

    The 676-word synthetic corpus yields ~701 possible merges, so a
    250-merge request completes without early-stop and therefore
    produces exactly two merge events.
    """
    events: list[ProgressEvent] = []
    corpus = _many_merges_corpus()
    train_bpe(corpus, 256 + 250, progress=events.append)
    assert events == [
        ProgressEvent(kind="start", merges_completed=0, merges_planned=250),
        ProgressEvent(kind="merge", merges_completed=100, merges_planned=250),
        ProgressEvent(kind="merge", merges_completed=200, merges_planned=250),
        ProgressEvent(kind="complete", merges_completed=250, merges_planned=250),
    ]
