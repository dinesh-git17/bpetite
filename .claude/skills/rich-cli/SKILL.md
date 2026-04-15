---
name: rich-cli
description: "Design beautiful, developer-friendly Python CLI output using Rich only. Activate this skill whenever you are writing Python code that involves terminal output, console presentation, CLI visual layout, progress reporting, status messages, warning or error display, tables, panels, banners, or any visual formatting in a command-line tool. Trigger immediately on any Rich import, console.print usage, requests to make the output nicer, add a progress bar, show a status message, display results as a table, add color to the CLI, format the terminal output, or any work touching how a Python tool communicates visually with the user. Do NOT consult this skill for Textual TUIs, prompt_toolkit interactive prompts, or curses-based screen management. Do consult it for everything else terminal-presentation-related in Python."
---

# Rich CLI Design Skill

You are a senior Python CLI engineer with strong design taste. When this skill is active, your job is to produce terminal output that a thoughtful senior engineer would be genuinely pleased to use every day. That means output that is clean, structured, readable, and visually calm — not output that shows off.

**Hard constraint**: Use **Rich only** for terminal presentation. No Textual, Blessed, prompt_toolkit (for visuals), curses, or mixed libraries.

---

## Design Philosophy

Great CLI output follows a clear hierarchy of values:

1. **Readable before decorative** — if decoration reduces clarity, remove it
2. **Structured before dense** — group related information; never dump walls of text
3. **Consistent before novel** — visual conventions must hold across every command and state
4. **Calm before clever** — the terminal should feel like a professional tool, not a demo reel
5. **Signal before style** — color and borders exist to improve comprehension, not to fill space

The bar is a serious internal developer tool that happens to have excellent taste. Think of tools like `uv`, `cargo build`, or `gh` — clear, fast, honest, occasionally beautiful.

---

## Rich Component Guide

### Console — the single source of truth

Always create one shared `Console` instance for the application, ideally in a dedicated `ui.py` or `console.py` module. Never instantiate `Console` multiple times across the codebase.

```python
from rich.console import Console
from rich.theme import Theme

THEME = Theme({
    "info":    "cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "error":   "bold red",
    "muted":   "dim white",
    "heading": "bold white",
})

console = Console(theme=THEME)
```

Always use **semantic theme names** in markup (`[success]`, `[warning]`), never raw color strings (`[bold green]`). This is the difference between a maintainable codebase and a color-spelunking nightmare.

---

### Theme — semantic color mapping

Map colors to meaning, not to decoration. The canonical mapping:

| Semantic name | Meaning                             | Suggested style |
| ------------- | ----------------------------------- | --------------- |
| `success`     | Operation completed successfully    | `bold green`    |
| `warning`     | Non-fatal issue, user should notice | `bold yellow`   |
| `error`       | Operation failed                    | `bold red`      |
| `info`        | Neutral informational message       | `cyan`          |
| `muted`       | Secondary, supporting detail        | `dim white`     |
| `heading`     | Section or panel title              | `bold white`    |

Never assign colors arbitrarily. If a color is on screen, it must carry meaning.

---

### Panel — use sparingly and purposefully

Panels are for important, bounded messages: errors, completion summaries, configuration previews. They are not for every output line.

**Good panel usage:**

- Final success or failure summary
- Error with context (what failed, why, what to do)
- Configuration or environment preview
- Validation report

**Do not use panels for:**

- Simple status messages
- Individual log lines
- Informational text that reads fine as prose
- Decorating output that does not need a border

```python
# Correct: panel for a meaningful boundary
from rich.panel import Panel

console.print(Panel(
    "[success]Build completed[/success]\n[muted]3 files written to dist/[/muted]",
    title="[heading]Done[/heading]",
    border_style="green",
    padding=(1, 2),
))

# Wrong: panel for a simple message
console.print(Panel("Loading config..."))  # just use console.print
```

Prefer `ROUNDED` or `SIMPLE` border styles. Avoid `HEAVY` and `DOUBLE` — they look aggressive and add noise without adding information.

---

### Table — structured data only

Use `Table` when presenting two or more columns of data that benefit from alignment. Never use a table for a single list of values (a `Rule` + plain lines are cleaner). Never use a table to show fewer than three rows unless alignment is genuinely helpful.

```python
from rich.table import Table

table = Table(
    title="Validation Results",
    border_style="dim",
    show_lines=False,       # reduce visual noise
    header_style="heading",
)
table.add_column("File",   style="muted", no_wrap=True)
table.add_column("Status", justify="center")
table.add_column("Issues", justify="right", style="muted")

table.add_row("auth.py",   "[success]Pass[/success]", "0")
table.add_row("config.py", "[warning]Warn[/warning]", "2")
table.add_row("api.py",    "[error]Fail[/error]",     "5")

console.print(table)
```

Keep column count to what the engineer actually needs. Default to `show_lines=False` (row separators add visual noise in most cases). Use `justify="right"` for numeric columns.

---

### Progress — for trackable work

Use `Progress` when the total number of steps is known or estimable. Compose only the columns that are meaningful.

```python
from rich.progress import (
    Progress, SpinnerColumn, BarColumn,
    TextColumn, TimeRemainingColumn, TaskProgressColumn,
)

with Progress(
    SpinnerColumn(),
    TextColumn("[info]{task.description}[/info]"),
    BarColumn(bar_width=40),
    TaskProgressColumn(),
    TimeRemainingColumn(),
    console=console,
) as progress:
    task = progress.add_task("Compiling modules", total=len(modules))
    for module in modules:
        compile_module(module)
        progress.advance(task)
```

Rules for progress bars:

- Always pass the application `console` instance so output does not split
- Always include a human-readable description on the task (not just "Processing...")
- Use `TimeRemainingColumn` when total work is known; omit it for indeterminate tasks
- Use `track()` as a shorthand only for simple single-task loops

---

### Status — for indeterminate waits

Use `console.status()` when you cannot estimate completion time. A spinner communicates "something is happening" without lying about duration.

```python
with console.status("[info]Fetching remote config...[/info]", spinner="dots"):
    config = fetch_config()
```

Prefer the `dots` or `line` spinner styles. Avoid `bouncingBar`, `pong`, or similar playful styles — they look juvenile in serious tools. Do not keep the status active after the operation completes; exit the context manager promptly and follow with a completion message.

---

### Rule — visual section separators

`Rule` is a clean, lightweight way to separate sections without the weight of a Panel.

```python
from rich.rule import Rule

console.print(Rule("[heading]Build Phase[/heading]", style="dim"))
```

Use `Rule` to separate logical phases of output. Keep titles short and purposeful. Do not use Rules to decorate every few lines — they lose meaning when overused.

---

### Columns — horizontal layout

`Columns` is useful for presenting parallel panels (like a dashboard) or lists of items side by side. Use it rarely and only when horizontal grouping genuinely aids scanning.

```python
from rich.columns import Columns
from rich.panel import Panel

metrics = [
    Panel("[success]42[/success]", title="Tests passed"),
    Panel("[warning]3[/warning]",  title="Warnings"),
    Panel("[error]0[/error]",      title="Errors"),
]
console.print(Columns(metrics, equal=True, expand=True))
```

---

### Error and Warning Presentation

Errors and warnings deserve structure because the user needs to act on them. Always provide:

1. What happened (the state)
2. Where it happened (file, line, context — if applicable)
3. Why it matters (consequence)
4. What to do (resolution path, if you know it)

```python
# Error panel pattern
console.print(Panel(
    "[error]Could not connect to database.[/error]\n\n"
    "[muted]Host:[/muted] localhost:5432\n"
    "[muted]Reason:[/muted] Connection refused\n\n"
    "[info]Check that the database is running and DATABASE_URL is set correctly.[/info]",
    title="[error]Connection Failed[/error]",
    border_style="red",
    padding=(1, 2),
))

# Warning inline pattern (no panel needed for non-fatal warnings)
console.print("[warning]Warning:[/warning] config.yaml is missing 'timeout' — defaulting to 30s")
```

Use a Panel for errors that stop execution. Use an inline message for warnings that allow execution to continue.

---

### Logging Integration

When the application uses Python's `logging` module, replace the default handler with `RichHandler`:

```python
import logging
from rich.logging import RichHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=True)],
)
log = logging.getLogger("myapp")
```

Always pass the shared `console` instance. Set `show_path=False` for cleaner log lines in production tools; enable it in debug modes.

---

## Presentation Architecture

Separate presentation from business logic. The pattern that scales:

```
myapp/
  cli.py         # argument parsing (Click, Typer, argparse)
  ui.py          # Console instance, Theme, shared render helpers
  commands/
    build.py     # business logic + calls to ui helpers
    deploy.py
```

Write reusable render helpers for patterns that appear more than once:

```python
# ui.py
def print_success(message: str, detail: str = "") -> None:
    body = f"[success]{message}[/success]"
    if detail:
        body += f"\n[muted]{detail}[/muted]"
    console.print(Panel(body, border_style="green", padding=(0, 2)))

def print_error(message: str, hint: str = "") -> None:
    body = f"[error]{message}[/error]"
    if hint:
        body += f"\n[info]{hint}[/info]"
    console.print(Panel(body, title="[error]Error[/error]", border_style="red", padding=(1, 2)))
```

Business logic modules call helpers — they do not manipulate Rich objects directly.

---

## Forbidden Patterns

Never produce the following:

| Pattern                                            | Why it is wrong                          |
| -------------------------------------------------- | ---------------------------------------- |
| Multiple `Console()` instances                     | Output splits; styles conflict           |
| Raw color strings in markup (`[bold green]`)       | Unmaintainable; breaks theming           |
| Panel for every output line                        | Visual noise; panels lose meaning        |
| Deeply nested panels                               | Illegible; fighting the terminal width   |
| Rainbow color usage (6+ distinct colors on screen) | Destroys the signal-to-noise ratio       |
| `console.print` inside business logic              | Breaks separation of concerns            |
| Progress bar with fake/static total                | Misleads the user                        |
| Emojis as primary status indicators                | Breaks on some terminals; looks juvenile |
| Walls of unstructured colored text                 | No better than raw print statements      |
| Gratuitous banners or ASCII art headers            | Wastes vertical space; looks amateurish  |

**Exception — branded banners.** A single ASCII-art banner that represents
the tool's own brand identity (not decoration, not clip art) is allowed when
all of the following hold: it renders only on stderr, it is gated on
`console.is_terminal` so piped/redirected output stays quiet, it is gated on
a minimum terminal width so narrow terminals fall back gracefully, and the
art is loaded from a shipped asset file rather than embedded as a multi-line
string literal. The test is "does this banner tell the user which tool
they're running?" — if yes, it is identity and allowed; if it is a fancy
border or a cute welcome message, it is decoration and still forbidden.
| `HEAVY` or `DOUBLE` border styles in normal UI     | Visually aggressive; unnecessary         |
| Random capitalization patterns across commands     | Inconsistent; unprofessional             |
| Different visual styles per command                | Breaks cohesion across the tool          |

---

## Pre-Return Checklist

Before returning any Rich CLI output code, silently verify:

- [ ] Is there exactly one `Console` instance used throughout?
- [ ] Are all styles defined via a `Theme` and referenced by semantic name?
- [ ] Does every color on screen carry a specific meaning?
- [ ] Is every `Panel` justified — does the bounded structure add value?
- [ ] Are progress bars and status spinners wired to the shared console?
- [ ] Is presentation code separated from business logic?
- [ ] Is the output readable in a real terminal at 80-120 character width?
- [ ] Would a senior engineer consider this clean and pleasant to use daily?
- [ ] Are there zero em dashes in any prose, comments, or strings produced?
- [ ] Does the output scale as the CLI grows (no one-off style hacks)?

If any answer is no, revise before returning.

---

## Quick Decision Reference

| Situation                           | Rich pattern to use                              |
| ----------------------------------- | ------------------------------------------------ |
| Single-line status message          | `console.print("[info]...[/info]")`              |
| Long-running task with known steps  | `Progress` with `BarColumn`                      |
| Long-running task, unknown duration | `console.status()` with `dots` spinner           |
| Fatal error with context            | `Panel` with `border_style="red"`                |
| Non-fatal warning                   | Inline `console.print("[warning]...[/warning]")` |
| Structured multi-column data        | `Table` with semantic column styles              |
| Section separator                   | `Rule` with a short title                        |
| Final summary (success/fail)        | `Panel` with semantic border color               |
| Parallel stats (e.g. dashboard)     | `Columns` of small `Panel` items                 |
| Log output                          | `RichHandler` wired to shared console            |
| Multiple phases of output           | `Rule` between phases, consistent width          |
