#!/usr/bin/env python3
"""TinyShakespeare corpus downloader for bpetite demos and benchmarks.

Fetches the canonical TinyShakespeare corpus from
``github.com/karpathy/char-rnn`` via stdlib :mod:`urllib.request` and
writes it to ``data/tinyshakespeare.txt`` at the repo root. The script
lives outside the ``bpetite`` package runtime path and is never imported
from ``src/bpetite/`` or ``bpetite._cli``; per the PRD, the core library
and CLI must not perform network calls, so network-bound helpers like
this one live in ``scripts/`` where the ``forbid-core-networking``
pre-commit hook does not reach.

The destination path is authoritative: ``data/tinyshakespeare.txt`` is
the one location downstream training, benchmark, and CI helpers check
for the corpus. Changing it would desynchronize ``.gitignore``, the
``forbid-generated-artifacts`` guard, and Phase 4 benchmark tooling.
Re-running the script overwrites the existing file so the most recent
fetch is always on disk. The destination is ``.gitignore``\\ d so the
downloaded corpus never ends up in version control.

This file supersedes the ``scripts/download_data.sh`` bash stopgap that
existed before Task 4-3; the shim was explicitly scaffolded as a
placeholder until this pure-Python port landed.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

_CORPUS_URL = (
    "https://raw.githubusercontent.com/karpathy/char-rnn/"
    "master/data/tinyshakespeare/input.txt"
)
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DESTINATION = _REPO_ROOT / "data" / "tinyshakespeare.txt"
_TIMEOUT_SECONDS = 30


def main() -> int:
    """Download the TinyShakespeare corpus to the authoritative path.

    Returns:
        ``0`` on a successful fetch and write, ``1`` on any network
        failure or filesystem write error. Human-readable status and
        error messages go to ``stderr``; ``stdout`` is intentionally
        left untouched so callers can pipe it without interleaving.
    """
    _DESTINATION.parent.mkdir(parents=True, exist_ok=True)

    sys.stderr.write(f"Downloading {_CORPUS_URL}\n")
    try:
        with urllib.request.urlopen(  # noqa: S310
            _CORPUS_URL, timeout=_TIMEOUT_SECONDS
        ) as response:
            payload = response.read()
    except urllib.error.URLError as exc:
        sys.stderr.write(f"Error: download failed: {exc}\n")
        return 1
    except TimeoutError as exc:
        sys.stderr.write(f"Error: download timed out: {exc}\n")
        return 1

    try:
        _DESTINATION.write_bytes(payload)
    except OSError as exc:
        sys.stderr.write(f"Error: could not write {_DESTINATION}: {exc}\n")
        return 1

    relative = _DESTINATION.relative_to(_REPO_ROOT)
    sys.stderr.write(f"Saved {len(payload):,} bytes to {relative}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
