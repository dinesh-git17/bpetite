"""Canonical GPT-2-style regex pre-tokenizer for the bpetite tokenizer.

Exposes :func:`pretokenize`, a pure function that splits arbitrary Unicode
text into a list of UTF-8 byte chunks using the canonical pre-tokenizer
pattern defined in :mod:`bpetite._constants`. The pattern is compiled
exactly once at module import time. No normalization, case folding, or
whitespace trimming occurs anywhere in this module.
"""

import regex

from bpetite._constants import PRETOKENIZER_PATTERN

_COMPILED_PATTERN: regex.Pattern[str] = regex.compile(PRETOKENIZER_PATTERN)


def pretokenize(text: str) -> list[bytes]:
    """Split text into UTF-8 byte chunks via the canonical pre-tokenizer regex.

    Args:
        text: Arbitrary Unicode input. May be empty.

    Returns:
        The regex match sequence in source order, with each match encoded
        as UTF-8 bytes. For empty input the result is ``[]``. Joining the
        result with ``b"".join`` reproduces ``text.encode("utf-8")`` exactly.
    """
    return [match.encode("utf-8") for match in _COMPILED_PATTERN.findall(text)]
