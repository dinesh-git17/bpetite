"""Byte-level BPE encoder for the bpetite tokenizer.

Exposes :func:`encode`, which extracts exact literal occurrences of
reserved special tokens from the input, pre-tokenizes each remaining
segment via :func:`bpetite._pretokenizer.pretokenize`, converts each
chunk to UTF-8 byte IDs, and applies the learned merges in rank order.
Within each merge rank the chunk is scanned once and every
non-overlapping adjacent occurrence of the ranked pair is replaced
left-to-right, matching the training-time replacement semantics from
FR-10.

This module is internal. The public :class:`bpetite.Tokenizer.encode`
API will delegate to :func:`encode` once Task 3-3 wires it up.
"""

from bpetite._pretokenizer import pretokenize

_BASE_VOCAB_SIZE = 256


def encode(
    text: str,
    merges: list[tuple[int, int]],
    special_tokens: dict[str, int],
) -> list[int]:
    """Encode text into byte-level BPE token IDs.

    Exact literal occurrences of any key in ``special_tokens`` are
    extracted first and emitted as their reserved ids. The remaining
    text segments are pre-tokenized with the canonical regex, each
    chunk is converted to its UTF-8 byte ids, and then the learned
    merges are applied in rank order. For each rank the chunk is
    scanned once and every non-overlapping adjacent match is replaced
    left-to-right, so ``[a, b, a, b]`` with merge ``(a, b)`` becomes
    ``[ab, ab]`` in a single pass at that rank.

    Args:
        text: Arbitrary Unicode input. May be empty.
        merges: Learned merge list in rank order. Element ``i`` is the
            pair ``(left_id, right_id)`` whose resulting merged token
            id is ``256 + i``.
        special_tokens: Mapping from each reserved special-token
            literal to its reserved token id. Only exact full-literal
            occurrences are extracted; partial strings such as
            ``"<|endoftext"`` flow through as ordinary text.

    Returns:
        The encoded token id sequence. ``encode("") == []``.
    """
    if not text:
        return []

    # Longest literal first so a hypothetical specials dict containing a
    # prefix of another literal matches the longer one at a given offset.
    sorted_specials = sorted(special_tokens.items(), key=lambda item: -len(item[0]))

    result: list[int] = []
    n = len(text)
    segment_start = 0
    i = 0
    while i < n:
        matched_id: int | None = None
        matched_len = 0
        for literal, token_id in sorted_specials:
            if text.startswith(literal, i):
                matched_id = token_id
                matched_len = len(literal)
                break
        if matched_id is not None:
            if segment_start < i:
                result.extend(_encode_ordinary(text[segment_start:i], merges))
            result.append(matched_id)
            i += matched_len
            segment_start = i
        else:
            i += 1
    if segment_start < n:
        result.extend(_encode_ordinary(text[segment_start:], merges))
    return result


def _encode_ordinary(
    text: str,
    merges: list[tuple[int, int]],
) -> list[int]:
    """Pre-tokenize and merge-apply a non-special text segment."""
    result: list[int] = []
    for chunk_bytes in pretokenize(text):
        tokens: list[int] = list(chunk_bytes)
        for rank, pair in enumerate(merges):
            tokens = _apply_merge(tokens, pair, _BASE_VOCAB_SIZE + rank)
        result.extend(tokens)
    return result


def _apply_merge(
    tokens: list[int],
    pair: tuple[int, int],
    new_id: int,
) -> list[int]:
    """Replace every non-overlapping occurrence of ``pair`` with ``new_id``.

    The scan is a single left-to-right pass. After a match at position
    ``i`` the cursor advances to ``i + 2``, so three identical adjacent
    tokens ``[x, x, x]`` with merge ``(x, x)`` become ``[xx, x]``,
    never ``[x, xx]``.
    """
    result: list[int] = []
    i = 0
    n = len(tokens)
    while i < n:
        if i + 1 < n and tokens[i] == pair[0] and tokens[i + 1] == pair[1]:
            result.append(new_id)
            i += 2
        else:
            result.append(tokens[i])
            i += 1
    return result
