#!/usr/bin/env python3
"""Forbid normalization and trimming calls in ``src/bpetite/``.

Per bpetite PRD FR-6 and CLAUDE.md: no normalization, case folding,
prefix-space insertion, or whitespace trimming anywhere in the tokenizer
pipeline. Violations silently corrupt ``decode(encode(text)) == text``.

Caught patterns (AST-based):

    <anything>.strip(...)       .lstrip(...)      .rstrip(...)
    <anything>.casefold(...)    .lower(...)       .upper(...)
    <anything>.title(...)       .capitalize(...)  .swapcase(...)
    unicodedata.normalize(...)
    import unicodedata
    from unicodedata import ...

Method calls are matched by attribute name. This may flag a method call on a
non-string object that happens to share one of these names; for the tokenizer
package that false-positive risk is acceptable because no such method should
be invoked in this code path anyway.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ui import Violation, render_failure  # noqa: E402

_RULE = "forbid-core-normalization"
_WHY = (
    "PRD FR-6 forbids normalization, case folding, prefix-space "
    "insertion, and whitespace trimming anywhere in the tokenizer "
    "pipeline. Any such transform silently breaks decode(encode(text)) "
    "== text."
)
_FIX = (
    "Operate on raw bytes or str without case or whitespace transforms. "
    "Preserve every source character exactly."
)

_FORBIDDEN_METHODS: frozenset[str] = frozenset(
    {
        "strip",
        "lstrip",
        "rstrip",
        "casefold",
        "lower",
        "upper",
        "title",
        "capitalize",
        "swapcase",
    }
)


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
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in _FORBIDDEN_METHODS:
                violations.append((node.lineno, f".{attr}() call"))
            elif (
                attr == "normalize"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "unicodedata"
            ):
                violations.append((node.lineno, "unicodedata.normalize(...) call"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "unicodedata":
                    violations.append((node.lineno, "import unicodedata"))
        elif isinstance(node, ast.ImportFrom) and node.module == "unicodedata":
            violations.append((node.lineno, "from unicodedata import ..."))
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
