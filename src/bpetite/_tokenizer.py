"""Public ``Tokenizer`` class for the bpetite tokenizer.

This module wires the private trainer, encoder, decoder, and
persistence layers into the single public class exposed by
:mod:`bpetite`. The class holds exactly three private fields — the
vocabulary, the ordered merge list, and the special-token map — and
delegates every public method to the corresponding internal function
without adding new behavior.

Instances are constructed via :meth:`Tokenizer.train` or
:meth:`Tokenizer.load`, not by calling ``__init__`` directly. The
constructor accepts already-normalized state so the two class methods
share a single code path; calling it by hand is permitted but not
part of the stable API and carries no validation beyond what the
trainer and loader already perform.
"""

from collections.abc import Sequence

from bpetite._decoder import decode as _decode
from bpetite._encoder import encode as _encode
from bpetite._persistence import load as _persistence_load
from bpetite._persistence import save as _persistence_save
from bpetite._trainer import train_bpe


class Tokenizer:
    """Deterministic byte-level BPE tokenizer.

    The public API is exactly:

    * :meth:`train` — learn merges from a text corpus
    * :meth:`encode` — text to token ids
    * :meth:`decode` — token ids back to text
    * :meth:`save` — persist to a Schema v1 JSON artifact
    * :meth:`load` — reconstruct from a Schema v1 JSON artifact
    """

    def __init__(
        self,
        vocab: dict[int, bytes],
        merges: list[tuple[int, int]],
        special_tokens: dict[str, int],
    ) -> None:
        """Store already-normalized tokenizer state.

        Prefer :meth:`train` or :meth:`load`. The constructor exists
        so both class methods can share a single wrapping path; it
        does not validate its arguments.
        """
        self._vocab = vocab
        self._merges = merges
        self._special_tokens = special_tokens

    @classmethod
    def train(cls, corpus: str, vocab_size: int) -> "Tokenizer":
        """Train a tokenizer on ``corpus`` up to ``vocab_size`` merges.

        Args:
            corpus: UTF-8 training text. May be empty.
            vocab_size: Target mergeable vocabulary size. Must be at
                least ``256``; callers pass ``256 + desired_merges``.

        Returns:
            A :class:`Tokenizer` instance holding the learned vocab,
            merges, and the reserved special-token mapping.

        Raises:
            ValueError: If ``vocab_size < 256``.
        """
        result = train_bpe(corpus, vocab_size)
        return cls(
            vocab=dict(result.vocab),
            merges=list(result.merges),
            special_tokens=dict(result.special_tokens),
        )

    def encode(self, text: str) -> list[int]:
        """Encode ``text`` into a sequence of token ids.

        Delegates to :func:`bpetite._encoder.encode` using the
        method argument ``text`` directly; no instance text state is
        involved.
        """
        return _encode(text, self._merges, self._special_tokens)

    def decode(self, token_ids: Sequence[int]) -> str:
        """Decode a sequence of token ids back to text.

        Raises:
            KeyError: If any id is not in this tokenizer's vocab.
            UnicodeDecodeError: If the concatenated token bytes are
                not valid UTF-8.
        """
        return _decode(token_ids, self._vocab)

    def save(self, path: str, overwrite: bool = False) -> None:
        """Persist this tokenizer to ``path`` as a Schema v1 artifact.

        Args:
            path: Destination file path. Parent directory must exist.
            overwrite: If ``False`` and ``path`` already exists, the
                save fails with :class:`FileExistsError`.

        Raises:
            FileNotFoundError: If the parent directory does not exist.
            FileExistsError: If ``path`` exists and ``overwrite`` is
                ``False``.
        """
        _persistence_save(
            path=path,
            vocab=self._vocab,
            merges=self._merges,
            special_tokens=self._special_tokens,
            overwrite=overwrite,
        )

    @classmethod
    def load(cls, path: str) -> "Tokenizer":
        """Load a tokenizer from a Schema v1 JSON artifact.

        Raises:
            KeyError: If the artifact is missing required top-level
                keys.
            ValueError: If the artifact fails any schema, shape,
                byte-range, or special-token invariant.
        """
        vocab, merges, special_tokens = _persistence_load(path)
        return cls(vocab=vocab, merges=merges, special_tokens=special_tokens)
