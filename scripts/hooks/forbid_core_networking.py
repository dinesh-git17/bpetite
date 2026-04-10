#!/usr/bin/env python3
"""Forbid direct networking imports in ``src/bpetite/``.

Per bpetite PRD: the core library and CLI perform no network calls. The only
networked helper is ``scripts/download_data.sh`` (to be ported to
``scripts/download_corpus.py`` in PRD task 4-3), which lives outside the
runtime path and is exempt from this check by scope.

**Enforcement scope.** The check is AST-based and catches only direct
``import`` and ``from ... import`` statements against the denylist. It does
not catch dynamic imports (``importlib.import_module``, ``__import__``),
``exec``/``eval``, or shelling out to networking binaries through
``subprocess``. Those patterns are fundamentally not detectable at the AST
layer; the guard's job is to catch the obvious direct-import mistake at
commit time. Real runtime isolation belongs to CI sandboxing, not a
pre-commit hook.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ui import Violation, render_failure  # noqa: E402

_RULE = "forbid-core-networking"
_WHY = (
    "The bpetite core library and CLI must not directly import "
    "networking modules. Direct imports are blocked here; dynamic "
    "imports and subprocess shells are out of AST scope and must be "
    "caught by CI or sandboxing."
)
_FIX = (
    "Remove the import or move the networked code into scripts/ "
    "outside the package runtime path."
)

_FORBIDDEN_MODULES: frozenset[str] = frozenset(
    {
        "socket",
        "socketserver",
        "ssl",
        "urllib",
        "http",
        "ftplib",
        "telnetlib",
        "smtplib",
        "smtpd",
        "poplib",
        "imaplib",
        "nntplib",
        "xmlrpc",
        "webbrowser",
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
    }
)


def _is_forbidden(module: str) -> bool:
    for forbidden in _FORBIDDEN_MODULES:
        if module == forbidden or module.startswith(forbidden + "."):
            return True
    return False


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
            for alias in node.names:
                if _is_forbidden(alias.name):
                    violations.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module and _is_forbidden(module):
                violations.append((node.lineno, f"from {module} import ..."))
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
