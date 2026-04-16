`bpetite` is a local Python library and CLI that implements a **deterministic byte-level BPE tokenizer** from scratch. It trains on UTF-8 text with a GPT-2-style pre-tokenizer, encodes and decodes losslessly, and persists a versioned single-file artifact that reloads with byte-for-byte fidelity.

Every decision, including how pairs are counted, how ties break, how merges apply, and how the encoder walks a chunk, lives in readable Python. No C extensions, no Rust, no external tokenizer library. One runtime dependency beyond the standard library: `regex`, used exclusively for the GPT-2 pre-tokenizer pattern.

It is **explicitly educational and local-only**. Not a production tokenizer service. Not aiming for GPT-2 token-ID parity. The goal is a codebase a senior reviewer can read end-to-end and see real understanding rather than a toy script.
