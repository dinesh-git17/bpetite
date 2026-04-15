"""Byte-level decoder for the bpetite tokenizer.

Exposes :func:`decode`, which maps each token id through the stored
vocabulary to its canonical bytes, concatenates the pieces, and
decodes the result once with UTF-8 strict mode. The byte-level BPE
invariant makes this safe: the encoder produces a sequence of token
ids whose concatenated bytes are exactly the UTF-8 encoding of the
input, so a single strict UTF-8 pass over the joined bytes
reconstructs the original text.

Decoding the reserved ``<|endoftext|>`` token id yields the literal
string ``"<|endoftext|>"`` because the trainer stores the literal's
UTF-8 bytes in the vocab entry for that id (see FR-24 and the
artifact schema).

This module is internal. The public
:class:`bpetite.Tokenizer.decode` API will delegate to
:func:`decode` once Task 3-3 wires it up.
"""

from collections.abc import Sequence


def decode(token_ids: Sequence[int], vocab: dict[int, bytes]) -> str:
    """Decode a sequence of BPE token ids back to text.

    Args:
        token_ids: The ordered token id sequence to decode. May be
            empty; ``decode([], vocab) == ""``.
        vocab: The tokenizer vocabulary mapping each known token id
            to its canonical bytes. Base byte ids ``0..255`` map to
            single-byte values, merge-derived ids ``256..`` map to
            the concatenated parent bytes in learned order, and the
            reserved special-token id maps to the UTF-8 bytes of its
            literal.

    Returns:
        The decoded string. Decoding an empty id sequence returns
        the empty string.

    Raises:
        KeyError: If any token id in ``token_ids`` is not a key of
            ``vocab``.
        UnicodeDecodeError: If the concatenated token bytes are not
            a valid UTF-8 sequence.
    """
    return b"".join(vocab[token_id] for token_id in token_ids).decode(
        "utf-8", errors="strict"
    )
