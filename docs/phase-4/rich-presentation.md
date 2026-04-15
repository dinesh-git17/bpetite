---
title: Rich Presentation Layer
description: Shared stderr console, themed palette, panel helpers, interactive gating, and the plain-progress-line design decision for the bpetite CLI.
slug: phase-4-rich-presentation
order: 32
category: Phase 4
published: true
---

# Rich Presentation Layer — shared stderr console, themed panels, lifecycle lines

## TL;DR

- Every human-readable element across `train`, `encode`, and `decode` is rendered
  through a single `Console` instance in `_ui.py`, constructed with `stderr=True` so no
  Rich markup can bleed into the stdout contract. The stdout contract is enforced
  structurally, not by convention.
- Three panel helpers (`render_banner`, `render_kv_box`, `render_error`) and one
  interactivity gate (`is_fully_interactive` / `banner_enabled`) are the full public
  surface of `_ui.py`. Every call site in `_cli.py` uses these helpers and never
  constructs its own `Console`.
- The train progress surface is three plain `console.print` lifecycle lines, not a
  live `rich.progress.Progress` bar. The `Progress` approach was attempted first and
  broke three independent edge cases (zero-merge runs, early-stop runs, invalid-vocab
  runs). Plain lines sidestep all of them.

## What lives here

| File                      | Purpose                                                                                                                                                              |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/bpetite/_ui.py`      | `console`, `_THEME`, `render_banner`, `render_box`, `render_kv_box`, `render_error`, `is_fully_interactive`, `banner_enabled`, `_kv_table`                           |
| `src/bpetite/_banner.txt` | The ASCII art `render_banner` prints when the terminal is wide enough and both streams are TTYs; loaded at call time via `_load_banner`, not cached at module import |
| `src/bpetite/_cli.py`     | Every call site for the panel helpers; the `_train_with_progress` closure that emits the three lifecycle lines via `console.print`                                   |

## Key invariants

| FR / Area | Invariant                                                                                                                            | Consequence if violated                                                                                                                                                                    |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| FR-34     | The shared `Console` targets stderr. Every Rich render in the CLI goes through this instance.                                        | Flipping `stderr=True` to `stderr=False` silently pushes styled output onto stdout, violating the stdout contract with invisible markup bytes.                                             |
| (local)   | User-supplied strings reach Rich tables wrapped in `Text(value)`, never as raw strings.                                              | Paths and error messages that contain literal `[` `]` are parsed as Rich markup; the render either silently rewrites the content or raises `MarkupError`.                                  |
| (local)   | `render_error` escapes `message` and `hint` through `rich.markup.escape` before interpolation into markup-bearing body templates.    | User-supplied exception strings containing `[red]foo[/red]` would execute as markup, producing misleading colored output or a `MarkupError` mid-render.                                    |
| (local)   | The banner renders only when `is_fully_interactive()` is true AND the terminal width is at least `_BANNER_MIN_COLUMNS` (95 columns). | Subprocess-captured stderr contains unexpected ASCII-art bytes; test byte-equality assertions break. Narrow terminals see a wrapped banner that looks broken.                              |
| (local)   | `is_fully_interactive` requires both `console.is_terminal` AND `sys.stdout.isatty()`.                                                | A run whose stdout is captured but whose stderr is still a TTY (pipe to `jq`, for example) would emit decorative panels; wrappers that treat any stderr as a warning signal would regress. |

## Walkthrough

### The public surface of `_ui.py`

`_ui.py` exposes eight names. Three panel helpers, one banner helper, two interactivity
predicates, one shared `Console`, and one private helper. All CLI rendering uses these
and nothing else.

| Name                     | Kind      | Purpose                                                                                                                             |
| ------------------------ | --------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `console`                | Singleton | The shared `Console(stderr=True, theme=_THEME, soft_wrap=False, highlight=False)`. Every Rich render must go through this instance. |
| `render_banner()`        | Function  | Print the centered ASCII banner to stderr if the terminal allows it. Silent if `banner_enabled()` returns `False`.                  |
| `render_box(...)`        | Function  | Render an arbitrary `RenderableType` body inside a full-width rounded `Panel`.                                                      |
| `render_kv_box(...)`     | Function  | Render a `(label, value)` row table inside a full-width rounded `Panel`. Thin wrapper over `render_box` + `_kv_table`.              |
| `render_error(...)`      | Function  | Render a red error `Panel` with an escaped message and an optional recovery hint.                                                   |
| `is_fully_interactive()` | Predicate | True only when both stderr and stdout are TTYs.                                                                                     |
| `banner_enabled()`       | Predicate | True when `is_fully_interactive()` is true AND terminal width is at least 95 columns.                                               |
| `_kv_table(rows)`        | Private   | Build a two-column `Table.grid` from a label/value list. Wraps each value in `Text` to suppress markup parsing.                     |

### The shared `Console`

The single load-bearing line in the entire presentation layer:

```python
# src/bpetite/_ui.py

console: Final[Console] = Console(
    stderr=True,
    theme=_THEME,
    soft_wrap=False,
    highlight=False,
)
```

- **`stderr=True`** is the structural guarantee that Rich output cannot reach stdout.
  Every panel, every `console.print`, every `render_*` helper inherits this target. A
  reviewer does not need to audit individual call sites for `sys.stdout` vs
  `sys.stderr`; the `Console` constructor does the audit once.
- **`theme=_THEME`** binds named styles to color codes. The named styles are defined
  once in `_THEME` and used by every render site, so changing a theme color updates
  the entire CLI consistently.
- **`soft_wrap=False`** disables Rich's default line-soft-wrapping. The configuration
  panel and completion panel have intentional column layouts; soft-wrap would reflow
  values and break alignment.
- **`highlight=False`** disables Rich's automatic syntax highlighting on printed text.
  Highlights on filenames or numbers would look like markup leaking into stderr.

### Themed palette

Ten named styles are defined in `_THEME` and used across the CLI:

| Style     | Definition     | Where it appears                                                                       |
| --------- | -------------- | -------------------------------------------------------------------------------------- |
| `info`    | `cyan`         | Lifecycle line bodies: `Training started: ...`, `Training merges: ...`                 |
| `success` | `bold green`   | The `Training complete: merges=...` lifecycle line; completion panel border is `green` |
| `warning` | `bold yellow`  | Reserved for warning panels; unused in v1                                              |
| `error`   | `bold red`     | `render_error` title and body; error panel border is `red`                             |
| `muted`   | `dim white`    | Reserved for secondary context; unused in v1                                           |
| `heading` | `bold white`   | Panel titles in `render_box`                                                           |
| `banner`  | `bold magenta` | The ASCII banner                                                                       |
| `accent`  | `bold cyan`    | Reserved for accent emphasis                                                           |
| `label`   | `bold cyan`    | Left column of every KV table (field names)                                            |
| `value`   | `white`        | Right column of every KV table (field values)                                          |

The style names are the public contract for CLI visual identity. Changing `info` from
`cyan` to `blue` would re-theme every lifecycle line without touching any render site.
Adding a new style requires adding it here; inline color literals in call sites are
not used anywhere in `_cli.py`.

### `render_kv_box` traced

The configuration and completion panels in `train` are the most-used Rich surface in
the CLI. Both render through `render_kv_box`:

```python
# src/bpetite/_ui.py

def _kv_table(rows: list[tuple[str, str]]) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="label", justify="left", no_wrap=True)
    table.add_column(style="value", justify="left", overflow="fold")
    for label, value in rows:
        table.add_row(label, Text(value))
    return table


def render_box(
    body: RenderableType,
    title: str,
    border_style: str = "cyan",
) -> None:
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
    render_box(_kv_table(rows), title=title, border_style=border_style)
```

The `Text(value)` wrap in `_kv_table` is load-bearing. Values passed to the CLI
frequently carry user-supplied paths like `data/tinyshakespeare-[test].json` or free-form
text containing literal `[` `]`. Without the wrap, Rich's markup parser would see the
brackets as style tags and either rewrite the rendered output silently or raise
`MarkupError` mid-render. Wrapping the value in `Text(...)` bypasses the parser entirely
and prints the string verbatim.

`padding=(1, 2)` adds one blank row above and below, two spaces of left/right padding.
`expand=True` makes the panel stretch to the terminal width so the border draws as a
full-width frame.

### `render_error` and markup escape

Error panels are the one place the CLI renders user-supplied text into a markup-bearing
template. Every source of user-supplied content — paths, exception strings, model
artifact JSON values — is escaped through `rich.markup.escape` before interpolation:

```python
# src/bpetite/_ui.py

def render_error(title: str, message: str, hint: str | None = None) -> None:
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
```

`title` is not escaped because every call site in `_cli.py` passes a hardcoded literal
(`"Input not found"`, `"Save blocked"`, `"Invalid vocab size"`, and so on). `message`
and `hint` are escaped because they carry dynamic content. A model artifact path
containing `[fancy]` characters can reach `message`; without the escape, Rich would
interpret `[fancy]` as a style tag, fail to find it in the theme, and raise
`MarkupError` at render time — turning an already-failing CLI run into a crash with a
Python traceback on stderr.

### The interactivity gate

`is_fully_interactive()` and `banner_enabled()` gate decorative output on the state of
both streams:

```python
# src/bpetite/_ui.py

def is_fully_interactive() -> bool:
    return console.is_terminal and sys.stdout.isatty()


def banner_enabled() -> bool:
    return is_fully_interactive() and console.size.width >= _BANNER_MIN_COLUMNS
```

The two-stream check is the non-obvious part. `console.is_terminal` alone would return
`True` for a run that pipes stdout through `jq` while stderr stays attached to a
terminal. That configuration is a machine-consumption mode: the user wants the stdout
JSON for further processing and any bytes on stderr would regress shell wrappers that
treat stderr as a warning signal. Requiring both streams to be TTYs forces the CLI to
stay quiet whenever stdout is captured, regardless of the stderr state.

`encode` and `decode` use this predicate directly to decide whether to render their
configuration and summary panels:

```python
# src/bpetite/_cli.py _cmd_encode (abbreviated)

interactive = is_fully_interactive()
if interactive:
    render_banner()
    render_kv_box(rows=[("Model", ...), ("Text", ...)], title="Encoding")

tokenizer = _load_model_or_exit(args.model)
ids = tokenizer.encode(args.text)

if interactive:
    render_kv_box(rows=[("Tokens", ...), ("Elapsed", ...)], title="Encoded", border_style="green")

sys.stdout.write(json.dumps(ids, separators=(",", ":")) + "\n")
```

Under `subprocess.run(stdout=PIPE)`, `sys.stdout.isatty()` returns `False`, `interactive`
evaluates to `False`, and both panels are skipped. Stderr receives nothing. Only the
single `sys.stdout.write` at the end runs, producing a clean JSON array the subprocess
test harness can parse and assert on. `train` does not gate its panels this way — the
train banner and both panels always render because the train stdout contract is always
the one-line JSON summary and the stderr output is not asserted against byte-equality
in the suite.

`render_banner()` additionally gates on terminal width: the ASCII art in `_banner.txt`
is 95 columns wide. A terminal narrower than that would wrap the art and produce a
broken visual. `banner_enabled()` returns `False` for narrow terminals and
`render_banner()` silently returns without printing.

### The progress surface decision

The train subcommand needs to render progress output during the merge loop. The
straightforward choice is `rich.progress.Progress` with a determinate bar whose total
equals `merges_planned`. That approach was attempted first and failed against three
independent edge cases.

**Edge case 1 — invalid `--vocab-size`.** If the caller passes `--vocab-size 100`,
`train_bpe` raises `ValueError` before emitting any `ProgressEvent`. A `Progress`
instance started before the trainer call and waiting to be advanced by the first event
would be left half-initialized: the live display has allocated a `TaskID` but nothing
has driven the bar forward. Cleaning up requires wrapping the entire trainer call in a
`with Progress(...) as prog:` block and catching `ValueError` inside, which nests the
error rendering inside the Rich live-display context and produces confused layering
(the error panel renders before the `Progress` display exits).

**Edge case 2 — zero-merge runs.** `--vocab-size 256` plans zero merges.
`merges_planned == 0`. A `Progress` bar with a total of zero is a Rich edge case:
depending on the render timing and terminal size, it either flashes `0/0` briefly
before the run completes or renders nothing at all. Either way the lifecycle events
fire in the wrong visual order (`start` shows an empty bar, `complete` replaces it
instantly), so the reader sees no evidence that training actually happened.

**Edge case 3 — early-stop runs.** Training a corpus whose distinct byte-pair space
runs out before reaching `vocab_size` triggers `if not pair_counts: break` in
`_trainer.py`. The loop exits early with `merges_completed < merges_planned`. A
`Progress` bar that has been advancing by individual merges is stuck at a non-full
state when the run ends. Cleaning up requires either calling `prog.update(task, total=merges_completed)`
to shrink the total (which re-renders the bar as full) or `prog.remove_task(task)` to
delete it entirely. Both approaches leave a scar in the rendered output that a reviewer
reading the stderr scroll cannot easily interpret.

**Current design: three plain `console.print` lines.**

```python
# src/bpetite/_cli.py _train_with_progress

def _on_event(event: ProgressEvent) -> None:
    if event.kind == "start":
        console.print(f"[info]Training started: planned={event.merges_planned}[/info]")
    elif event.kind == "merge":
        console.print(
            f"[info]Training merges: {event.merges_completed} / {event.merges_planned}[/info]"
        )
    else:  # complete
        console.print(
            f"[success]Training complete: merges={event.merges_completed}[/success]"
        )
```

Each event maps to exactly one `console.print` line in a specific theme style. The
lines are ordinary stderr output: they do not share a live render context, they do not
allocate a `TaskID`, and they do not need cleanup on error. All three edge cases
disappear:

- Invalid vocab size: `train_bpe` raises `ValueError` before the `start` event fires,
  so no lifecycle line is ever emitted. `_train_with_progress` catches the
  `ValueError` and calls `_fail`, which renders an error panel. Clean.
- Zero-merge runs: the trainer fires `start` with `merges_planned=0`, then `complete`
  with `merges_completed=0`. Two ordinary lines on stderr, each of which reads cleanly
  on its own.
- Early-stop runs: the trainer fires `complete` with `merges_completed < merges_planned`.
  The completion lifecycle line reads `Training complete: merges=21272`, which is
  unambiguous and does not need to revisit any earlier render.

Do not reintroduce a live `Progress` bar. If richer mid-training feedback is ever
needed, start by reading this section and the three edge cases above before touching
`_train_with_progress`.

### The rendered stderr output of a train run

A `train` invocation against `data/tinyshakespeare.txt` at `vocab_size=512` produces
the following stderr output in order:

1. **Banner** (if the terminal is fully interactive and at least 95 columns wide) —
   the ASCII art from `_banner.txt`, magenta, centered.
2. **Configuration panel** — a rounded cyan Panel titled `Training` with four rows:
   `Input`, `Vocab size`, `Output`, `Force overwrite`.
3. **Training started lifecycle line** — `Training started: planned=256`, cyan.
4. **Training merges lifecycle lines** — `Training merges: 100 / 256`, then `Training merges: 200 / 256`. Cyan. One line every 100 completed merges.
5. **Training complete lifecycle line** — `Training complete: merges=256`, bold green.
6. **Completion panel** — a rounded green Panel titled `Training complete` with six
   rows: `Corpus bytes`, `Requested vocab size`, `Actual mergeable vocab size`,
   `Special tokens`, `Elapsed`, `Saved to`.

The only stdout write happens at the end of step 6, after the panel renders: the
five-key JSON summary on one line with a trailing newline.

## Failure modes

| Failure                                                         | Consequence                                                                                                | Caught by                                                                     |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `Console(stderr=True)` flipped to `stderr=False`                | Styled panels render on stdout, corrupting the machine-readable contract with invisible markup bytes       | Every CLI contract test that asserts `json.loads(result.stdout)` succeeds     |
| Panel value rendered without `Text()` wrap                      | Paths or text containing `[` `]` parsed as markup; render corrupted or `MarkupError` raised                | Code-level constraint at `_ui.py:107`                                         |
| `render_error` without `markup_escape` on message/hint          | User-supplied exception strings with `[...]` execute as markup; misleading colored output or `MarkupError` | Code-level constraint at `_ui.py:147-149`                                     |
| Banner rendered in non-interactive mode                         | Subprocess-captured stderr contains unexpected ASCII-art bytes; byte-equality assertions break             | `is_fully_interactive()` + `banner_enabled()` gate at `_ui.py:78-88`          |
| Decorative encode/decode panels rendered under `subprocess.run` | Stderr bytes appear in captured output; wrappers that treat stderr as a warning signal regress             | `is_fully_interactive()` gate in `_cmd_encode`/`_cmd_decode`                  |
| Live `rich.progress.Progress` reintroduced                      | Zero-merge, early-stop, and invalid-vocab edge cases render incorrectly or crash                           | Design decision documented above; no automated test — enforced by code review |

### Silent failure modes called out by name

**The two-stream interactivity check is the non-obvious part.** An implementation that
gates on `console.is_terminal` alone would emit decorative panels when stdout is piped
through a tool like `jq`. That configuration is exactly the one where silence matters
most: the user is consuming the JSON output programmatically and any bytes on stderr
would regress a shell wrapper. The `sys.stdout.isatty()` half of the check catches
this case. Both halves must be true.

**The banner minimum-columns check is separate from the interactivity check.** A
terminal that is interactive but only 80 columns wide would wrap the 95-column banner
and render broken ASCII art. `banner_enabled()` combines `is_fully_interactive()` with
a `console.size.width >= _BANNER_MIN_COLUMNS` check. A reviewer editing `_banner.txt`
must update `_BANNER_MIN_COLUMNS` in the same commit if the art width changes, or
narrow-terminal users will see the banner suddenly start rendering incorrectly.

## Related reading

- [CLI Contract](cli-contract.md) — the channel discipline the shared `Console`
  enforces structurally; the progress-callback wiring that produces the three
  lifecycle lines documented above.
- [Phase 3 Public Tokenizer API](../phase-3/public-api.md) — the five-method contract
  the CLI wraps; the reason `_cmd_train` cannot attach the progress callback to
  `Tokenizer.train` and must go through internal `train_bpe` instead.
- [`src/bpetite/_ui.py`](../../src/bpetite/_ui.py) — full presentation-layer source,
  ~160 lines.
- [`src/bpetite/_banner.txt`](../../src/bpetite/_banner.txt) — ASCII art; any edit
  must be paired with a review of `_BANNER_MIN_COLUMNS` in `_ui.py`.
- [`src/bpetite/_cli.py`](../../src/bpetite/_cli.py) — every call site for the panel
  helpers, the `_train_with_progress` callback closure.
- [`docs/bpetite-prd-v2.md`](../bpetite-prd-v2.md) — FR-33, FR-34 (channel discipline
  that the presentation layer reinforces structurally).
