"""Shared Rich presentation layer for the bpetite command-line interface.

All human-readable output across ``train``, ``encode``, and ``decode`` is
routed through the single :data:`console` instance defined in this module.
The console is constructed with ``stderr=True`` so every Rich render — the
banner, configuration panels, progress bars, and error panels — lands on
stderr without polluting the machine-readable contract on stdout.

Machine-readable results (``train`` JSON summary, ``encode`` compact JSON
array, ``decode`` raw text) are **not** rendered through this module. They
are written via ``sys.stdout.write`` directly in ``_cli.py`` so no Rich
markup, theme, or styling can bleed into the stdout contract enforced by
FR-33 and FR-34.

The banner is a deliberate brand identity element. It renders only when
stderr is an interactive terminal and the terminal is wide enough to hold
the art cleanly; in any non-interactive context (pipes, redirects, CI
capture, subprocess tests) the banner is suppressed so the stderr stream
stays quiet and test assertions remain stable.
"""

import sys
from pathlib import Path
from typing import Final

from rich.box import ROUNDED
from rich.console import Console, RenderableType
from rich.markup import escape as markup_escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

_BANNER_PATH: Final[Path] = Path(__file__).parent / "_banner.txt"
_BANNER_MIN_COLUMNS: Final[int] = 95

_THEME: Final[Theme] = Theme(
    {
        "info": "cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "muted": "dim white",
        "heading": "bold white",
        "banner": "bold magenta",
        "accent": "bold cyan",
        "label": "bold cyan",
        "value": "white",
    }
)

console: Final[Console] = Console(
    stderr=True,
    theme=_THEME,
    soft_wrap=False,
    highlight=False,
)


def _load_banner() -> str:
    return _BANNER_PATH.read_text(encoding="utf-8").rstrip("\n")


def is_fully_interactive() -> bool:
    """Return ``True`` only when both stderr and stdout are TTYs.

    The CLI uses this gate to decide whether decorative output is
    appropriate for the current run. When stdout is captured for any
    reason — shell command substitution, ``subprocess.run(stdout=PIPE)``,
    file redirection — the caller is in machine-consumption mode and the
    decorative stderr surface should stay quiet so wrappers that treat any
    stderr bytes as a warning signal do not regress. Both streams must be
    TTYs to consider the run fully interactive.
    """
    return console.is_terminal and sys.stdout.isatty()


def banner_enabled() -> bool:
    """Return ``True`` when the banner can render cleanly on this stream.

    The check combines a full-interactivity probe with a minimum-width
    floor: a non-interactive run (CI, pipes, subprocess capture, captured
    stdout) yields ``False`` so redirected output stays free of ornament,
    and a terminal narrower than the art yields ``False`` so the banner
    never wraps.
    """
    return is_fully_interactive() and console.size.width >= _BANNER_MIN_COLUMNS


def render_banner() -> None:
    """Print the centered ASCII banner to stderr if the terminal allows it."""
    if not banner_enabled():
        return
    console.print(_load_banner(), style="banner", justify="center")
    console.print()


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="label", justify="left", no_wrap=True)
    table.add_column(style="value", justify="left", overflow="fold")
    for label, value in rows:
        # Wrap value in Text so Rich does not parse `[...]` as markup. Values
        # frequently carry user-supplied paths and free-form text that may
        # contain literal bracket characters; markup parsing would either
        # silently rewrite the content or raise MarkupError mid-render.
        table.add_row(label, Text(value))
    return table


def render_box(
    body: RenderableType,
    title: str,
    border_style: str = "cyan",
) -> None:
    """Render ``body`` inside a full-width rounded Panel on stderr."""
    console.print(
        Panel(
            body,
            title=f"[heading]{title}[/heading]",
            border_style=border_style,
            box=ROUNDED,
            padding=(1, 2),
            expand=True,
        )
    )


def render_kv_box(
    rows: list[tuple[str, str]],
    title: str,
    border_style: str = "cyan",
) -> None:
    """Render a label/value table inside a full-width Panel on stderr."""
    render_box(_kv_table(rows), title=title, border_style=border_style)


def render_error(title: str, message: str, hint: str | None = None) -> None:
    """Render a fatal-error Panel on stderr with optional recovery hint.

    ``message`` and ``hint`` are escaped through ``rich.markup.escape`` before
    being interpolated into the markup-bearing body so that user-supplied
    content (paths, exception strings, model artifact text) cannot inject or
    break Rich markup. ``title`` is left as-is because every call site passes
    a hardcoded literal.
    """
    body = f"[error]{markup_escape(message)}[/error]"
    if hint:
        body += f"\n\n[info]{markup_escape(hint)}[/info]"
    console.print(
        Panel(
            body,
            title=f"[error]{title}[/error]",
            border_style="red",
            box=ROUNDED,
            padding=(1, 2),
            expand=True,
        )
    )
