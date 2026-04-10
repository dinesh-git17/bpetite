#!/usr/bin/env python3
"""Require ``/commitall``-mediated approval for every commit.

Commits in this repository must go through ``scripts/commitall.sh`` (or the
``/commitall`` slash command), which displays the diff and requires explicit
human approval before invoking ``git commit``. This guard blocks any commit
that bypasses that flow, including a raw ``git commit`` or an agent-initiated
commit that did not clear the approval prompt.

Mechanism: the approval flow touches a sentinel file at
``.git/COMMIT_APPROVED`` just before running ``git commit`` and removes it on
exit via a trap. This hook checks for that sentinel and renders a failure
panel (via ``_ui.render_failure``) when it is missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ui import Violation, render_failure

_RULE = "require-commitall-approval"
_WHY = (
    "Direct commits are blocked in this repository. Every commit must "
    "go through scripts/commitall.sh (or the /commitall slash command), "
    "which displays the diff and requires explicit approval before "
    "writing the commit."
)
_FIX = (
    "Abort this commit and run `bash scripts/commitall.sh` instead. "
    "Never create or delete .git/COMMIT_APPROVED manually."
)

_SENTINEL = Path(".git/COMMIT_APPROVED")


def main() -> int:
    if _SENTINEL.is_file():
        return 0
    violations = [
        Violation(
            path="(this commit)",
            detail="no approval sentinel at .git/COMMIT_APPROVED",
        )
    ]
    render_failure(rule=_RULE, violations=violations, why=_WHY, fix=_FIX)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
