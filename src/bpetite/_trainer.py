"""Deterministic byte-level BPE trainer for the bpetite tokenizer.

This module is internal; the public :class:`bpetite.Tokenizer` API will
delegate to :func:`train_bpe` once it is wired up in Task 3-3. The trainer:

* pre-tokenizes the corpus via :func:`bpetite._pretokenizer.pretokenize`;
* represents each unique pre-token as a tuple of base byte token IDs
  (0..255) together with its multiplicity from the corpus;
* at each merge step counts adjacent pair frequencies per pre-token
  (pairs never bridge pre-token boundaries), selects the most frequent
  pair, ties broken by the lexicographically smallest tuple (FR-10);
* applies the merge non-overlapping left-to-right so that
  ``(x, x, x)`` with merge ``(x, x)`` becomes ``(xx, x)``, never
  ``(x, xx)``;
* stops early when no mergeable pairs remain and returns the actual
  learned mergeable vocabulary size rather than padding with placeholders;
* reserves the single special token ``<|endoftext|>`` (FR-14) at the
  first integer id past the mergeable vocabulary, per FR-15.

The trainer never special-cases ``<|endoftext|>`` during training. If
the literal appears in the corpus it flows through pre-tokenization and
merging like any other text; reservation happens only after merge
training completes.

Example:
    A trace of the first merge step for
    ``train_bpe("ab ab ab", vocab_size=258)``:

    * pre-tokenization yields ``[b"ab", b" ab", b" ab"]``;
    * unique pre-tokens with multiplicity:
      ``{(97, 98): 1, (32, 97, 98): 2}``;
    * pair counts weighted by multiplicity:
      ``{(97, 98): 3, (32, 97): 2}``;
    * the best pair is ``(97, 98)`` (count 3, no tie), minted as
      token id ``256`` with bytes ``b"ab"``.

    See ``docs/phase-2/core-algorithm.md`` for the full walkthrough.
"""

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from bpetite._constants import END_OF_TEXT_TOKEN
from bpetite._pretokenizer import pretokenize

_BASE_VOCAB_SIZE = 256
_PROGRESS_EVERY = 100


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """A snapshot of training progress.

    Attributes:
        kind: Lifecycle marker. ``"start"`` fires once before the merge
            loop begins, ``"merge"`` fires every ``100`` completed
            merges, and ``"complete"`` fires once after the loop exits
            (including early-stop).
        merges_completed: Number of merges appended to the merge list
            at the moment the event fires.
        merges_planned: The maximum number of merges the caller
            requested, equal to ``vocab_size - 256``. Early-stop can
            leave ``merges_completed < merges_planned`` at completion.
    """

    kind: Literal["start", "merge", "complete"]
    merges_completed: int
    merges_planned: int


type ProgressCallback = Callable[[ProgressEvent], None]


@dataclass(frozen=True, slots=True)
class TrainerResult:
    """The output of :func:`train_bpe`.

    Attributes:
        merges: The ordered merge list. Each element is a
            ``(left_id, right_id)`` pair of token IDs. The list order
            is the merge rank: the first element is rank ``0`` and
            corresponds to token id ``256``, the second is rank ``1``
            at token id ``257``, and so on.
        vocab: Mapping from token id to its canonical bytes. Keys
            ``0..255`` are the base bytes; keys
            ``256..mergeable_vocab_size - 1`` are the merge-derived
            tokens in the order they were learned; the key
            ``mergeable_vocab_size`` maps to the UTF-8 bytes of the
            reserved special token literal
            (``"<|endoftext|>".encode("utf-8")``) so that decoding
            any emitted special-token id through ``vocab`` yields
            the literal string per FR-24 and the artifact schema.
        mergeable_vocab_size: ``256 + len(merges)``. May be smaller
            than the ``vocab_size`` requested by the caller if
            early-stop fired before the quota was filled. The ``vocab``
            attribute holds one additional entry past this value for
            the reserved special token; ``vocab_size`` in the PRD
            sense (mergeable only) excludes that entry.
        special_tokens: Mapping from the special token literal to its
            id. Special ids live past ``mergeable_vocab_size`` and the
            corresponding ``vocab`` entries are guaranteed to exist.
    """

    merges: tuple[tuple[int, int], ...]
    vocab: Mapping[int, bytes]
    mergeable_vocab_size: int
    special_tokens: Mapping[str, int]


def train_bpe(
    corpus: str,
    vocab_size: int,
    *,
    progress: ProgressCallback | None = None,
) -> TrainerResult:
    """Train a deterministic byte-level BPE tokenizer.

    The trainer pre-tokenizes ``corpus``, counts adjacent byte pairs
    within each pre-token, and repeatedly merges the most frequent
    pair (ties broken lexicographically) until either ``vocab_size``
    has been reached or no mergeable pairs remain.

    Args:
        corpus: UTF-8 training text. May be empty.
        vocab_size: Target mergeable vocabulary size. Must be at least
            ``256``. Callers pass ``256 + desired_merges``.
        progress: Optional progress callback. Called once with
            ``kind="start"`` before the merge loop, once every ``100``
            completed merges with ``kind="merge"``, and once with
            ``kind="complete"`` after the loop exits.

    Returns:
        A :class:`TrainerResult` with the merge list, the complete
        vocabulary, the actual mergeable vocab size (possibly less
        than requested due to early-stop), and the special-token
        reservation.

    Raises:
        ValueError: If ``vocab_size`` is less than ``256``.
    """
    if vocab_size < _BASE_VOCAB_SIZE:
        msg = f"vocab_size must be >= {_BASE_VOCAB_SIZE}, got {vocab_size}"
        raise ValueError(msg)

    pretoken_counts: Counter[bytes] = Counter(pretokenize(corpus))

    # Carry the multiplicity on each unique word so pair counting runs
    # over unique pre-tokens rather than every corpus position. Keys
    # are tuples of base byte IDs; iterating ``bytes`` yields ``int``.
    words: dict[tuple[int, ...], int] = {
        tuple(pretoken): count for pretoken, count in pretoken_counts.items()
    }

    vocab: dict[int, bytes] = {i: bytes([i]) for i in range(_BASE_VOCAB_SIZE)}
    merges: list[tuple[int, int]] = []
    merges_planned = vocab_size - _BASE_VOCAB_SIZE

    if progress is not None:
        progress(
            ProgressEvent(
                kind="start",
                merges_completed=0,
                merges_planned=merges_planned,
            )
        )

    for step in range(merges_planned):
        pair_counts = _count_pairs(words)
        if not pair_counts:
            break

        best_pair = _select_best_pair(pair_counts)

        new_id = _BASE_VOCAB_SIZE + step
        vocab[new_id] = vocab[best_pair[0]] + vocab[best_pair[1]]
        merges.append(best_pair)
        words = _apply_merge_to_words(words, best_pair, new_id)

        if progress is not None and (step + 1) % _PROGRESS_EVERY == 0:
            progress(
                ProgressEvent(
                    kind="merge",
                    merges_completed=step + 1,
                    merges_planned=merges_planned,
                )
            )

    if progress is not None:
        progress(
            ProgressEvent(
                kind="complete",
                merges_completed=len(merges),
                merges_planned=merges_planned,
            )
        )

    mergeable_vocab_size = _BASE_VOCAB_SIZE + len(merges)
    # Reserve the special token ID past the mergeable range AND populate
    # ``vocab`` at that ID with the UTF-8 bytes of the literal. FR-24
    # requires ``decode([special_id]) == "<|endoftext|>"``, and the
    # decoder resolves every ID through a single ``vocab`` lookup
    # (PRD line 205), so the entry has to live in ``vocab`` itself, not
    # in a parallel special-token-only fallback dict.
    special_token_id = mergeable_vocab_size
    vocab[special_token_id] = END_OF_TEXT_TOKEN.encode("utf-8")
    special_tokens: Mapping[str, int] = {END_OF_TEXT_TOKEN: special_token_id}

    return TrainerResult(
        merges=tuple(merges),
        vocab=vocab,
        mergeable_vocab_size=mergeable_vocab_size,
        special_tokens=special_tokens,
    )


def _count_pairs(
    words: Mapping[tuple[int, ...], int],
) -> Counter[tuple[int, int]]:
    """Count adjacent pair frequencies, respecting pre-token boundaries.

    Pairs are counted independently per unique word and weighted by the
    word's corpus multiplicity. A pair never bridges word boundaries:
    the last token of word A and the first token of word B are never a
    candidate because each word's pair stream is computed via
    :func:`itertools.pairwise` in isolation.
    """
    counts: Counter[tuple[int, int]] = Counter()
    for word, weight in words.items():
        for pair in pairwise(word):
            counts[pair] += weight
    return counts


def _select_best_pair(
    pair_counts: Mapping[tuple[int, int], int],
) -> tuple[int, int]:
    """Pick the most frequent pair, tie-broken by lexicographic minimum.

    ``min`` with the key ``(-count, pair)`` selects the highest count
    first and, on ties, the lexicographically smallest pair using
    standard Python tuple ordering (FR-10).
    """
    return min(
        pair_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )[0]


def _apply_merge_to_words(
    words: Mapping[tuple[int, ...], int],
    pair: tuple[int, int],
    new_id: int,
) -> dict[tuple[int, ...], int]:
    """Apply ``pair -> new_id`` to every word, accumulating duplicates."""
    merged_words: dict[tuple[int, ...], int] = {}
    for word, weight in words.items():
        merged_word = _apply_merge_to_word(word, pair, new_id)
        merged_words[merged_word] = merged_words.get(merged_word, 0) + weight
    return merged_words


def _apply_merge_to_word(
    word: tuple[int, ...],
    pair: tuple[int, int],
    new_id: int,
) -> tuple[int, ...]:
    """Merge ``pair`` into ``new_id`` within ``word``, non-overlapping LTR.

    Given three identical adjacent tokens ``(x, x, x)`` and a merge
    ``(x, x)``, the result is ``(xx, x)`` and not ``(x, xx)``: the
    first pair is consumed, the index advances past the merge point,
    and the second (now-overlapping) candidate is skipped.
    """
    result: list[int] = []
    i = 0
    n = len(word)
    while i < n:
        if i + 1 < n and word[i] == pair[0] and word[i + 1] == pair[1]:
            result.append(new_id)
            i += 2
        else:
            result.append(word[i])
            i += 1
    return tuple(result)
