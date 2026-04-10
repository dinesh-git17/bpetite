#!/usr/bin/env python3
"""Forbid direct ``import re`` in the tokenizer implementation.

Per bpetite PRD FR-4: the canonical pre-tokenizer pattern uses Unicode
property escapes (``\\p{L}``, ``\\p{N}``) which stdlib ``re`` does not
support. The package must import the third-party ``regex`` module instead.

**Enforcement scope.** Only direct ``import re`` and ``from re import ...``
statements are caught. Dynamic access via ``importlib.import_module('re')``
or ``__import__('re')`` is outside AST scope. The guard's job is to catch
the obvious direct-import mistake; broader runtime isolation is not the
goal of a pre-commit hook.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ui import Violation, render_failure

_RULE = "forbid-stdlib-re-in-tokenizer"
_WHY = (
    "PRD FR-4 requires the `regex` package because the canonical "
    "pre-tokenizer pattern uses Unicode property escapes (\\p{L}, "
    "\\p{N}) which stdlib `re` does not support. Only direct imports "
    "are caught; dynamic access is out of AST scope."
)
_FIX = "Replace `import re` with `import regex`."


def _check_file(path: Path) -> list[tuple[int, str]]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            violations.extend(
                (node.lineno, "import re") for alias in node.names if alias.name == "re"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "re":
            violations.append((node.lineno, "from re import ..."))
    return violations


def main(argv: list[str]) -> int:
    violations: list[Violation] = []
    for arg in argv:
        path = Path(arg)
        for lineno, message in _check_file(path):
            violations.append(Violation(path=str(path), lineno=lineno, detail=message))
    if not violations:
        return 0
    render_failure(rule=_RULE, violations=violations, why=_WHY, fix=_FIX)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
