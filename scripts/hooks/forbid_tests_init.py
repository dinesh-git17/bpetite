#!/usr/bin/env python3
"""Fail if any staged path is ``tests/__init__.py``.

Per bpetite CLAUDE.md and PRD: tests must import via the installed
src-layout package path. An ``__init__.py`` under ``tests/`` turns the
test tree into a Python package, which is unnecessary under pytest's
``importlib`` import mode and can introduce duplicate imports when test
module names collide across directories. It is also a common symptom of
"tests reach into the source tree directly", which defeats the src/
layout's isolation guarantee.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ui import Violation, render_failure

_RULE = "forbid-tests-init"
_WHY = (
    "Tests must import via the installed src/ package path. An "
    "__init__.py under tests/ turns the test tree into a package, "
    "which is unnecessary under pytest's importlib import mode and can "
    "create duplicate imports when test module names collide."
)
_FIX = "Delete tests/__init__.py and re-stage the commit."


def main(argv: list[str]) -> int:
    offenders = [p for p in argv if Path(p).as_posix() == "tests/__init__.py"]
    if not offenders:
        return 0
    violations = [Violation(path=p, detail="file must not exist") for p in offenders]
    render_failure(rule=_RULE, violations=violations, why=_WHY, fix=_FIX)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
