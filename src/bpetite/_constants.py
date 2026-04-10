"""Shared constants for the bpetite tokenizer.

This module is the single source of truth for values that must not drift
between the pre-tokenizer, trainer, encoder, and persistence layer.
"""

PRETOKENIZER_PATTERN: str = (
    r"""'(?:[sdmt]|ll|ve|re)| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+"""
)

SCHEMA_VERSION: int = 1

END_OF_TEXT_TOKEN: str = "<|endoftext|>"  # noqa: S105
