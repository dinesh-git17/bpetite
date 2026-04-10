#!/usr/bin/env python3
"""Determinism gate for the bpetite tokenizer artifact.

Trains on ``tests/fixtures/tiny.txt`` twice via the CLI and compares the
resulting JSON artifacts byte-for-byte. Exit code is ``0`` on a successful
match and ``1`` on any divergence, with a unified diff printed to ``stderr``
for the failing case.

The script is consumed by ``.github/workflows/determinism.yml`` but is also
directly runnable locally. It does not import the ``bpetite`` package; it
drives the installed console entry point through ``uv run`` so that the CI
path exercises the same artifact-write code path an end user would hit.
"""

from __future__ import annotations

import difflib
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "tiny.txt"
VOCAB_SIZE = "260"


def _train(output: Path) -> None:
    cmd = [
        "uv",
        "run",
        "bpetite",
        "train",
        "--input",
        str(FIXTURE),
        "--vocab-size",
        VOCAB_SIZE,
        "--output",
        str(output),
        "--force",
    ]
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def main() -> int:
    if not FIXTURE.exists():
        sys.stderr.write(
            f"fixture missing: {FIXTURE} (cannot run determinism gate)\n",
        )
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        a = Path(tmp) / "artifact-a.json"
        b = Path(tmp) / "artifact-b.json"
        _train(a)
        _train(b)
        bytes_a = a.read_bytes()
        bytes_b = b.read_bytes()
        if bytes_a == bytes_b:
            sys.stdout.write(
                f"determinism ok: {len(bytes_a)} bytes identical across two runs\n",
            )
            return 0

        sys.stderr.write(
            "determinism failure: artifacts differ between two runs on the "
            "same corpus and vocab-size\n",
        )
        diff = difflib.unified_diff(
            bytes_a.decode("utf-8", errors="replace").splitlines(keepends=True),
            bytes_b.decode("utf-8", errors="replace").splitlines(keepends=True),
            fromfile="run-1",
            tofile="run-2",
        )
        sys.stderr.writelines(diff)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
