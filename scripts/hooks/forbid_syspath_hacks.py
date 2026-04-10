#!/usr/bin/env python3
"""Forbid sys.path mutations and PYTHONPATH writes in repo code.

Per bpetite CLAUDE.md and PRD: tests must import from the installed package
path; nothing in the repo may mutate import resolution at runtime. This
script uses AST matching with simple alias resolution so it cannot be
bypassed by merely renaming the ``sys`` or ``os`` imports.

Caught patterns (direct form):
    sys.path.{insert,append,extend,pop,clear,remove}(...)
    sys.path = ...
    sys.path[...] = ...
    sys.path += ...
    os.environ["PYTHONPATH"] = ...
    os.environ["PYTHONPATH"] += ...
    os.putenv("PYTHONPATH", ...)

Caught via alias resolution:
    import sys as s; s.path.append(...)
    import os as o; o.environ["PYTHONPATH"] = "x"
    import os as o; o.putenv("PYTHONPATH", "x")
    from sys import path; path.append(...)
    from os import environ; environ["PYTHONPATH"] = "x"
    from os import putenv; putenv("PYTHONPATH", "x")

**Enforcement scope.** This guard resolves simple module-level aliases
created by ``import`` / ``from ... import`` statements in the same file.
It does NOT track local rebindings (``x = sys; x.path.append(...)``),
dynamic attribute access (``getattr(sys, "path").append(...)``), or
string-based code execution (``exec("sys.path.append(...)")``). Those
patterns are out of AST scope; determined bypass is always possible and is
not the guard's job to prevent. The guard catches the common accidental
case and the common aliased case, which covers the realistic failure
modes for a deterministic tokenizer project.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ui import Violation, render_failure  # noqa: E402

_RULE = "forbid-syspath-hacks"
_WHY = (
    "Tests must import from the installed src/ package path. Mutating "
    "sys.path or PYTHONPATH breaks reproducible imports and hides "
    "packaging regressions. Common aliases are tracked; dynamic access "
    "(getattr, exec, etc.) is out of AST scope."
)
_FIX = (
    "Remove the mutation and use absolute imports through the installed "
    "console script entry point instead."
)

_SYS_PATH_MUTATORS: frozenset[str] = frozenset(
    {"insert", "append", "extend", "pop", "clear", "remove"}
)


class _Visitor(ast.NodeVisitor):
    """AST visitor that flags sys.path / PYTHONPATH mutations.

    Resolves simple module-level aliases created by ``import`` and
    ``from ... import`` statements before checking each reference.
    Aliases are collected as the tree is walked, which is valid because
    Python requires a name to be bound before it is used.
    """

    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []
        # Local name -> canonical module name ("sys" or "os").
        # Populated by `import sys` and `import sys as s`.
        self._module_aliases: dict[str, str] = {}
        # Local name -> (module, attribute). Populated by
        # `from sys import path`, `from os import environ`, `from os import putenv`.
        self._attr_imports: dict[str, tuple[str, str]] = {}

    # ----- alias collection ------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name in ("sys", "os"):
                local = alias.asname or alias.name
                self._module_aliases[local] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module in ("sys", "os"):
            for alias in node.names:
                local = alias.asname or alias.name
                self._attr_imports[local] = (module, alias.name)
        self.generic_visit(node)

    # ----- reference resolution --------------------------------------------

    def _resolves_to_sys_path(self, node: ast.AST) -> bool:
        """Return True if ``node`` is a reference to ``sys.path``."""
        # `path` after `from sys import path`
        if isinstance(node, ast.Name):
            return self._attr_imports.get(node.id) == ("sys", "path")
        # `sys.path` or `s.path` where `s` aliases `sys`
        if isinstance(node, ast.Attribute) and node.attr == "path":
            if isinstance(node.value, ast.Name):
                return self._module_aliases.get(node.value.id) == "sys"
        return False

    def _resolves_to_os_environ(self, node: ast.AST) -> bool:
        """Return True if ``node`` is a reference to ``os.environ``."""
        if isinstance(node, ast.Name):
            return self._attr_imports.get(node.id) == ("os", "environ")
        if isinstance(node, ast.Attribute) and node.attr == "environ":
            if isinstance(node.value, ast.Name):
                return self._module_aliases.get(node.value.id) == "os"
        return False

    def _is_pythonpath_subscript(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Subscript):
            return False
        if not self._resolves_to_os_environ(node.value):
            return False
        sliced = node.slice
        return isinstance(sliced, ast.Constant) and sliced.value == "PYTHONPATH"

    def _is_os_putenv_call(self, node: ast.Call) -> bool:
        """Match ``os.putenv("PYTHONPATH", ...)`` and alias variants."""
        func = node.func
        target_is_putenv = False
        # `os.putenv(...)` or `o.putenv(...)` where `o` aliases `os`
        if isinstance(func, ast.Attribute) and func.attr == "putenv":
            if isinstance(func.value, ast.Name):
                target_is_putenv = self._module_aliases.get(func.value.id) == "os"
        # `putenv(...)` after `from os import putenv`
        elif isinstance(func, ast.Name):
            target_is_putenv = self._attr_imports.get(func.id) == ("os", "putenv")
        if not target_is_putenv:
            return False
        return (
            bool(node.args)
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "PYTHONPATH"
        )

    # ----- rule checks -----------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _SYS_PATH_MUTATORS
            and self._resolves_to_sys_path(node.func.value)
        ):
            self.violations.append((node.lineno, f"sys.path.{node.func.attr}(...)"))
        if self._is_os_putenv_call(node):
            self.violations.append((node.lineno, 'os.putenv("PYTHONPATH", ...)'))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if self._resolves_to_sys_path(target):
                self.violations.append((node.lineno, "sys.path = ..."))
            elif isinstance(target, ast.Subscript) and self._resolves_to_sys_path(
                target.value
            ):
                self.violations.append((node.lineno, "sys.path[...] = ..."))
            elif self._is_pythonpath_subscript(target):
                self.violations.append((node.lineno, 'os.environ["PYTHONPATH"] = ...'))
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if self._resolves_to_sys_path(node.target):
            self.violations.append((node.lineno, "sys.path += ..."))
        elif self._is_pythonpath_subscript(node.target):
            self.violations.append((node.lineno, 'os.environ["PYTHONPATH"] += ...'))
        self.generic_visit(node)


def _check_file(path: Path) -> list[tuple[int, str]]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    visitor = _Visitor()
    visitor.visit(tree)
    return visitor.violations


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
