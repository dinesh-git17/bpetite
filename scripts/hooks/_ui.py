"""Shared terminal UI helper for bpetite repo-local hook scripts.

Stdlib-only. Portable across macOS and Linux. Emits ANSI escape codes and
Unicode light-single-line box-drawing characters (U+2500..U+253C, the set
with the most consistent font coverage across modern terminals).

Output discipline
-----------------
- All styled output goes to ``sys.stderr``. Pre-commit captures both streams
  and only displays them on failure, so this keeps stdout clean.
- Colors are gated behind a three-way precedence check:
    1. ``NO_COLOR`` env var set to any non-empty value -> colors off
       (per https://no-color.org spec).
    2. ``FORCE_COLOR`` env var set to any non-empty value -> colors on
       (de-facto convention shared by Node.js and common Python CLIs).
    3. Otherwise fall back to ``stream.isatty()``.
- Visible width is computed with ANSI escape codes stripped so that the
  panel borders align correctly even when content is colored.

Public contract
---------------
``Violation``
    A dataclass capturing one violation: path, optional line number, and
    a short detail string (e.g. the offending import or call).

``render_failure``
    Renders a full-enclosure panel summarizing a rule violation set. The
    panel has a title bar containing the rule name and violation count, a
    body listing each violation, and a trailing ``help:`` paragraph that
    explains the rule and the fix.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass
from typing import TextIO

_ESC = "\x1b["
_RESET = f"{_ESC}0m"
_BOLD = f"{_ESC}1m"
_DIM = f"{_ESC}2m"
_RED = f"{_ESC}31m"
_CYAN = f"{_ESC}36m"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Light single-line box-drawing set (U+2500..U+253C). Most portable per
# research against modern terminal font coverage.
_TL = "\u250c"  # top-left corner
_TR = "\u2510"  # top-right corner
_BL = "\u2514"  # bottom-left corner
_BR = "\u2518"  # bottom-right corner
_H = "\u2500"  # horizontal
_V = "\u2502"  # vertical

_PANEL_MAX_WIDTH = 88
_PANEL_MIN_WIDTH = 60
_ELLIPSIS = "\u2026"


@dataclass(frozen=True)
class Violation:
    """A single rule violation to render inside a panel body."""

    path: str
    detail: str
    lineno: int | None = None


def _visible_len(text: str) -> int:
    """Length of ``text`` with ANSI escape codes stripped."""
    return len(_ANSI_RE.sub("", text))


def _color_enabled(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR", "") != "":
        return False
    if os.environ.get("FORCE_COLOR", "") != "":
        return True
    return stream.isatty()


def _panel_width() -> int:
    try:
        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    except OSError:
        cols = 80
    return max(_PANEL_MIN_WIDTH, min(cols, _PANEL_MAX_WIDTH))


def _stylize(text: str, codes: tuple[str, ...], *, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{''.join(codes)}{text}{_RESET}"


def _truncate_visible(text: str, limit: int) -> str:
    """Trim ``text`` (which may contain ANSI) so its visible length fits."""
    if _visible_len(text) <= limit:
        return text
    # The AST-based hooks never embed ANSI inside detail strings, so plain
    # character-level truncation is safe here.
    plain = _ANSI_RE.sub("", text)
    if limit <= 1:
        return _ELLIPSIS
    return plain[: limit - 1] + _ELLIPSIS


def render_failure(
    *,
    rule: str,
    violations: list[Violation],
    why: str,
    fix: str,
    stream: TextIO | None = None,
) -> None:
    """Render a polished hook failure panel.

    Args:
        rule: The hook id / rule name (e.g. ``forbid-core-networking``).
        violations: One entry per concrete violation.
        why: A single-line rationale explaining why the rule exists.
        fix: A single-line actionable remediation.
        stream: Target stream. Defaults to ``sys.stderr``.
    """
    out = stream if stream is not None else sys.stderr
    color = _color_enabled(out)

    def styled(text: str, *codes: str) -> str:
        return _stylize(text, codes, enabled=color)

    width = _panel_width()
    inner_slot = width - 4  # two border chars + one pad char on each side

    count = len(violations)
    noun = "violation" if count == 1 else "violations"
    count_str = f"{count} {noun}"

    # Title bar layout: ┌─ <rule> <dashes> <count_str> ─┐
    # Fixed visible characters: ┌─ + space + rule + space + dashes + space
    # + count_str + space + ─ + ┐  =  8 + len(rule) + len(count_str) + dashes
    title_fixed = 8 + len(rule) + len(count_str)
    dash_count = max(0, width - title_fixed)
    top_bar = (
        styled(_TL + _H + " ", _DIM)
        + styled(rule, _BOLD, _RED)
        + styled(" " + _H * dash_count + " ", _DIM)
        + styled(count_str, _DIM, _RED)
        + styled(" " + _H + _TR, _DIM)
    )

    v_border = styled(_V, _DIM)

    def body_line(content: str, content_visible_len: int) -> str:
        pad = max(0, inner_slot - content_visible_len)
        return f"{v_border} {content}{' ' * pad} {v_border}"

    body: list[str] = [body_line("", 0)]

    # Violation rows. Long locations are truncated from the left with an
    # ellipsis so the right border always aligns.
    loc_detail_gap = 2  # two spaces between location and detail
    min_detail_budget = 8
    for v in violations:
        loc_full = f"{v.path}:{v.lineno}" if v.lineno is not None else v.path
        max_loc_len = max(10, inner_slot - loc_detail_gap - min_detail_budget)
        if len(loc_full) > max_loc_len:
            loc_plain = _ELLIPSIS + loc_full[-(max_loc_len - 1) :]
        else:
            loc_plain = loc_full
        detail_budget = max(1, inner_slot - len(loc_plain) - loc_detail_gap)
        detail_trimmed = _truncate_visible(v.detail, detail_budget)
        visible_len = len(loc_plain) + loc_detail_gap + _visible_len(detail_trimmed)
        line_text = f"{styled(loc_plain, _CYAN)}  {detail_trimmed}"
        body.append(body_line(line_text, visible_len))

    body.append(body_line("", 0))

    # Help paragraph: "help: <why> <fix>" with hanging indent under the "h".
    help_label_visible = "help: "
    help_wrap_width = max(10, inner_slot - len(help_label_visible))
    help_text = f"{why.strip()} {fix.strip()}"
    wrapped = textwrap.wrap(help_text, width=help_wrap_width)
    if wrapped:
        first = wrapped[0]
        styled_first = f"{styled('help:', _BOLD, _CYAN)} {first}"
        body.append(body_line(styled_first, len(help_label_visible) + len(first)))
        hang = " " * len(help_label_visible)
        for cont in wrapped[1:]:
            visible_len = len(hang) + len(cont)
            body.append(body_line(f"{hang}{cont}", visible_len))

    body.append(body_line("", 0))

    bottom_bar = styled(_BL + _H * (width - 2) + _BR, _DIM)

    out.write("\n")
    out.write(top_bar + "\n")
    for entry in body:
        out.write(entry + "\n")
    out.write(bottom_bar + "\n")
    out.write("\n")
