Most engineers use tokenizers as opaque dependencies. `tiktoken`, `sentencepiece`, whatever ships with the model: you import it, you pass text in, you get integers out, and you never look inside. That is fine for building applications. It is weak for foundational ML engineering.

I wanted the tokenization layer to stop being a black box for me, so I rebuilt it. Not a port or a wrapper, but an implementation written from the byte level up, small enough to hold in my head and strict enough to prove it works. Deterministic training. Byte-perfect round-trips on every input: ASCII, whitespace, empty strings, UTF-8 emoji, the reserved special token. A versioned on-disk artifact that reloads without behavioural drift. `mypy --strict` clean. Every merge and every tie-break covered by tests.

The result is a codebase I can reason about completely, and that a reviewer can read end-to-end in an afternoon. That is the whole point.
