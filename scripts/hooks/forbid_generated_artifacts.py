#!/usr/bin/env python3
"""Forbid committing generated corpora and tokenizer artifacts.

Per bpetite task list (Task 1-1) and PRD: generated files are build outputs,
not source. Committing them drifts the repo away from reproducibility and
inflates the history.

Forbidden patterns (matched as repo-root-anchored paths):

    data/tinyshakespeare.txt       exact; downloaded corpus (PRD task 2-6)
    data/tinyshakespeare-*.json    generated tokenizer artifacts
    data/*.json                    any JSON directly under data/
    tokenizer.json                 repo-root artifact (PRD default CLI output)

**Anchoring.** Patterns match the full path-segment tuple one-for-one.
``tokenizer.json`` matches only ``tokenizer.json`` at the repository root,
not ``fixtures/tokenizer.json`` or any other nested occurrence.
``data/*.json`` matches direct children of the top-level ``data/``
directory only, not ``data/sub/foo.json`` or ``nested/data/foo.json``.
This is deliberately stricter than ``PurePosixPath.match``, whose single-
component glob matches from the right and therefore blocks any basename
``tokenizer.json`` anywhere in the tree.
"""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ui import Violation, render_failure  # noqa: E402

_RULE = "forbid-generated-artifacts"
_WHY = (
    "Generated corpora and trained tokenizer artifacts are build "
    "outputs. They must not enter version control."
)
_FIX = (
    "Unstage the file with `git restore --staged <path>` and ensure "
    ".gitignore excludes it."
)

_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    "data/tinyshakespeare.txt",
    "data/tinyshakespeare-*.json",
    "data/*.json",
    "tokenizer.json",
)


def _matches_anchored(path: str, pattern: str) -> bool:
    """Return True if ``path`` matches ``pattern`` as a repo-root anchored rule.

    Both the path and the pattern are split into path segments. The match
    succeeds only if the segment counts are equal and every pair of
    corresponding segments matches under :func:`fnmatch.fnmatchcase`.
    """
    path_parts = PurePosixPath(path).parts
    pattern_parts = PurePosixPath(pattern).parts
    if len(path_parts) != len(pattern_parts):
        return False
    return all(
        fnmatch.fnmatchcase(segment, pattern_segment)
        for segment, pattern_segment in zip(path_parts, pattern_parts)
    )


def _matched_pattern(path: str) -> str | None:
    for pattern in _FORBIDDEN_PATTERNS:
        if _matches_anchored(path, pattern):
            return pattern
    return None


def main(argv: list[str]) -> int:
    violations: list[Violation] = []
    for arg in argv:
        path = PurePosixPath(arg).as_posix()
        pattern = _matched_pattern(path)
        if pattern is not None:
            violations.append(
                Violation(path=path, detail=f"matches forbidden pattern '{pattern}'")
            )
    if not violations:
        return 0
    render_failure(rule=_RULE, violations=violations, why=_WHY, fix=_FIX)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
