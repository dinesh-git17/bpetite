"""Static site generator for the bpetite documentation site.

Produces a ``_site/`` tree containing:
    * ``index.html``          the landing page, with an auto-discovered docs list
    * ``docs/<slug>.html``    one page per published markdown doc
    * ``404.html``            styled not-found page
    * ``assets/``             css, js, fonts, favicon, copied verbatim
    * ``.nojekyll``           disables GitHub Pages' Jekyll pipeline

Markdown is rendered at build time with ``markdown-it-py`` (CommonMark +
anchors + tables + deflist + strikethrough) and syntax-highlighted with
Pygments. ``html=False`` is non-negotiable: it refuses raw HTML in source,
which eliminates the primary XSS vector. Jinja2 autoescape handles every
frontmatter string.

Auto-discovery: ``docs/*.md`` files with ``published: true`` in their YAML
frontmatter are published. Everything else in ``docs/`` stays private.

CLI:
    python docs/site/build.py --out _site
"""

from __future__ import annotations

import argparse
import datetime as dt
import html as html_lib
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter
import pygments
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.deflist import deflist_plugin
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

SITE_DIR = Path(__file__).resolve().parent
DOCS_DIR = SITE_DIR.parent
REPO_ROOT = DOCS_DIR.parent
TEMPLATES_DIR = SITE_DIR / "templates"
ASSETS_DIR = SITE_DIR / "assets"
CONTENT_DIR = SITE_DIR / "content"

REPO_URL = "https://github.com/dinesh-git17/bpetite"
SITE_TITLE = "bpetite"
SITE_DESCRIPTION = (
    "Deterministic byte-level BPE tokenizer, written from scratch in pure Python."
)
WORDS_PER_MINUTE = 220
DEFAULT_CATEGORY = "Documentation"

INVARIANTS: list[dict[str, str]] = [
    {"key": "Language", "val": "Pure Python 3.12"},
    {"key": "Runtime dep", "val": "regex (pre-tokenizer only)"},
    {"key": "Determinism", "val": "Same corpus, same artifact"},
    {"key": "Round-trip", "val": "decode(encode(text)) == text, always"},
    {"key": "Artifact", "val": "Single versioned JSON file"},
    {"key": "API surface", "val": "One export: Tokenizer"},
    {"key": "Quality gate", "val": "pytest + ruff + mypy --strict"},
]


@dataclass(frozen=True)
class Heading:
    """A heading extracted from a parsed markdown document."""

    level: int
    text: str
    anchor: str


@dataclass
class DocPage:
    """A single published document, ready for template rendering."""

    slug: str
    title: str
    description: str
    category: str
    order: int
    source_path: str
    body_html: str
    headings: list[Heading] = field(default_factory=list)
    word_count: int = 0
    reading_time: str = ""
    updated: str = ""


def build_markdown() -> MarkdownIt:
    """Construct the MarkdownIt renderer with html disabled and plugins loaded."""
    md = (
        MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True})
        .enable("table")
        .enable("strikethrough")
        .use(anchors_plugin, min_level=2, max_level=4, permalink=False)
        .use(deflist_plugin)
    )
    md.options["highlight"] = _highlight
    return md


def _highlight(code: str, lang: str, _attrs: str) -> str:
    """Pygments-backed syntax highlighter for markdown-it-py.

    Returns a complete ``<figure class="code">`` block. markdown-it-py
    uses the returned HTML verbatim and skips its default pre/code wrapper.
    """
    try:
        lexer = get_lexer_by_name(lang) if lang else TextLexer()
    except ClassNotFound:
        lexer = TextLexer()
    formatter = HtmlFormatter(nowrap=False, cssclass="highlight", nobackground=True)
    rendered = pygments.highlight(code, lexer, formatter)
    label = html_lib.escape(lang or "text")
    return f'<figure class="code"><figcaption>{label}</figcaption>{rendered}</figure>\n'


def extract_headings(md: MarkdownIt, text: str) -> tuple[str, list[Heading]]:
    """Render markdown to HTML and extract an ordered list of headings."""
    env: dict[str, Any] = {}
    tokens = md.parse(text, env)
    headings: list[Heading] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "heading_open" and tok.tag in {"h2", "h3", "h4"}:
            level = int(tok.tag[1])
            anchor = tok.attrs.get("id", "") if tok.attrs else ""
            heading_text = ""
            if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                heading_text = tokens[i + 1].content
            if anchor and heading_text:
                headings.append(
                    Heading(level=level, text=heading_text, anchor=str(anchor))
                )
        i += 1
    body_html = md.renderer.render(tokens, md.options, env)
    return body_html, headings


def git_last_modified(path: Path) -> str:
    """Return the last-modified date (YYYY-MM-DD) of a file from git log.

    Falls back to the file's mtime if git has no record of the path
    (unstaged or untracked).
    """
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "-1",
                "--format=%ad",
                "--date=short",
                "--",
                str(path),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        stamp = result.stdout.strip()
        if stamp:
            return stamp
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)
    return mtime.strftime("%Y-%m-%d")


def git_short_sha() -> str:
    """Return the short commit SHA of the current HEAD, or ``unknown``."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        sha = result.stdout.strip()
        return sha if sha else "unknown"
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unknown"


def reading_time(word_count: int) -> str:
    """Return a human-friendly reading-time string for a word count."""
    minutes = max(1, round(word_count / WORDS_PER_MINUTE))
    return f"{minutes} min read"


def count_words(text: str) -> int:
    """Rough word count on raw markdown source (good enough for a badge)."""
    return len([chunk for chunk in text.split() if chunk])


def _slug_from_path(path: Path) -> str:
    stem = path.stem.lower()
    safe = [c if c.isalnum() else "-" for c in stem]
    return "".join(safe).strip("-") or "doc"


def discover_published_docs(md: MarkdownIt) -> list[DocPage]:
    """Scan ``docs/**/*.md`` and return every doc with ``published: true``.

    Traverses subdirectories recursively. Files under ``docs/site/``
    (templates, assets, content) are excluded.
    """
    pages: list[DocPage] = []
    for md_path in sorted(DOCS_DIR.rglob("*.md")):
        if SITE_DIR in md_path.parents:
            continue
        post = frontmatter.load(md_path)
        if not post.metadata.get("published", False):
            continue
        meta = post.metadata
        slug = str(meta.get("slug") or _slug_from_path(md_path))
        title = str(meta.get("title") or md_path.stem)
        description = str(meta.get("description") or "")
        category = str(meta.get("category") or DEFAULT_CATEGORY)
        order = int(meta.get("order") or 99)
        body_html, headings = extract_headings(md, post.content)
        words = count_words(post.content)
        rel_source = md_path.relative_to(REPO_ROOT).as_posix()
        page = DocPage(
            slug=slug,
            title=title,
            description=description,
            category=category,
            order=order,
            source_path=rel_source,
            body_html=body_html,
            headings=headings,
            word_count=words,
            reading_time=reading_time(words),
            updated=git_last_modified(md_path),
        )
        pages.append(page)
    pages.sort(key=lambda p: (p.order, p.title.lower()))
    return pages


def render_content_fragment(md: MarkdownIt, path: Path) -> str:
    """Render a non-doc markdown file (landing content) to raw HTML."""
    if not path.exists():
        msg = f"content fragment missing: {path}"
        raise FileNotFoundError(msg)
    text = path.read_text(encoding="utf-8")
    return str(md.render(text))


def copy_assets(out_dir: Path) -> None:
    """Mirror ``docs/site/assets/`` into ``<out>/assets/``."""
    dest = out_dir / "assets"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ASSETS_DIR, dest)


def write_file(path: Path, content: str) -> None:
    """Write text content to ``path``, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _doc_for_template(page: DocPage) -> dict[str, Any]:
    return {
        "slug": page.slug,
        "title": page.title,
        "description": page.description,
        "category": page.category,
        "reading_time": page.reading_time,
        "updated": page.updated,
        "word_count": page.word_count,
        "source_path": page.source_path,
    }


def _base_context(build_sha: str, build_date: str) -> dict[str, Any]:
    return {
        "repo_url": REPO_URL,
        "build_sha": build_sha,
        "build_date": build_date,
        "build_year": str(dt.datetime.now(tz=dt.UTC).year),
        "page_title": SITE_TITLE,
        "page_description": SITE_DESCRIPTION,
    }


def render_landing(
    env: Environment,
    md: MarkdownIt,
    pages: list[DocPage],
    out_dir: Path,
    build_sha: str,
    build_date: str,
) -> None:
    """Render the landing page to ``<out>/index.html``."""
    overview_html = render_content_fragment(md, CONTENT_DIR / "overview.md")
    why_html = render_content_fragment(md, CONTENT_DIR / "why.md")
    ctx = _base_context(build_sha, build_date) | {
        "base": ".",
        "page_title": f"{SITE_TITLE} — {SITE_DESCRIPTION}",
        "overview_html": overview_html,
        "why_html": why_html,
        "invariants": INVARIANTS,
        "docs": [_doc_for_template(p) for p in pages],
    }
    rendered = env.get_template("landing.html").render(**ctx)
    write_file(out_dir / "index.html", rendered)


def render_doc_pages(
    env: Environment,
    pages: list[DocPage],
    out_dir: Path,
    build_sha: str,
    build_date: str,
) -> None:
    """Render each published doc to ``<out>/docs/<slug>.html``."""
    template = env.get_template("doc.html")
    for page in pages:
        ctx = _base_context(build_sha, build_date) | {
            "base": "..",
            "page_title": f"{page.title} — {SITE_TITLE}",
            "page_description": page.description or SITE_DESCRIPTION,
            "doc": _doc_for_template(page),
            "toc": [
                {"level": h.level, "text": h.text, "anchor": h.anchor}
                for h in page.headings
            ],
            "body": page.body_html,
        }
        rendered = template.render(**ctx)
        write_file(out_dir / "docs" / f"{page.slug}.html", rendered)


def render_not_found(
    env: Environment,
    out_dir: Path,
    build_sha: str,
    build_date: str,
) -> None:
    """Render a styled 404 page."""
    ctx = _base_context(build_sha, build_date) | {
        "base": ".",
        "page_title": f"not found — {SITE_TITLE}",
    }
    body = (
        '<section class="section">'
        '<div class="section__head">'
        '<span class="section__kicker">404</span>'
        '<h2 class="section__title">not found</h2>'
        "</div>"
        '<p class="section__prose">'
        "the page you&rsquo;re looking for isn&rsquo;t here. "
        '<a href="index.html">return home</a>.'
        "</p>"
        "</section>"
    )
    rendered = env.from_string(_NOT_FOUND_TEMPLATE).render(**ctx, body=body)
    write_file(out_dir / "404.html", rendered)


_NOT_FOUND_TEMPLATE = """{% extends "base.html" %}
{% block content %}{{ body | safe }}{% endblock %}
"""


def _iter_output_paths(out_dir: Path) -> Iterator[Path]:
    return (p for p in out_dir.rglob("*") if p.is_file())


def _audit_no_inline_handlers(out_dir: Path) -> None:
    """Belt-and-braces CSP sanity check on the generated site.

    Fails the build if any emitted HTML contains an inline ``<script>``
    body, a ``style=`` attribute, or a DOM ``on*=`` handler — all of
    which would force ``'unsafe-inline'`` in the CSP we've committed to.
    """
    offenders: list[str] = []
    inline_script_re = "<script>"
    for path in _iter_output_paths(out_dir):
        if path.suffix.lower() != ".html":
            continue
        text = path.read_text(encoding="utf-8").lower()
        if inline_script_re in text:
            offenders.append(f"{path}: inline <script> body")
        if ' style="' in text or " style='" in text:
            offenders.append(f"{path}: inline style= attribute")
        offenders.extend(
            f"{path}: inline {handler} handler"
            for handler in ("onclick=", "onload=", "onerror=", "onmouseover=")
            if handler in text
        )
    if offenders:
        joined = "\n  - ".join(offenders)
        msg = f"CSP audit failed:\n  - {joined}"
        raise RuntimeError(msg)


def build_site(out_dir: Path) -> None:
    """Build the full site into ``out_dir``.

    Clears ``out_dir`` first so stale files from previous builds never
    linger. Runs a CSP audit at the end; the build fails if any emitted
    HTML contains inline script, style, or event handlers.
    """
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    md = build_markdown()
    env = _build_env()
    pages = discover_published_docs(md)

    build_sha = git_short_sha()
    build_date = dt.datetime.now(tz=dt.UTC).strftime("%Y-%m-%d")

    render_landing(env, md, pages, out_dir, build_sha, build_date)
    render_doc_pages(env, pages, out_dir, build_sha, build_date)
    render_not_found(env, out_dir, build_sha, build_date)
    copy_assets(out_dir)
    write_file(out_dir / ".nojekyll", "")

    _audit_no_inline_handlers(out_dir)

    rel_out = (
        out_dir.resolve().relative_to(REPO_ROOT) if out_dir.is_absolute() else out_dir
    )
    print(f"[build] wrote site to {rel_out}")
    print(f"[build] published {len(pages)} doc(s)")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bpetite-site-build",
        description="Build the bpetite documentation site.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "_site",
        help="Output directory for the generated site (default: ./_site).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    args = _parse_args(argv)
    out_dir: Path = args.out if args.out.is_absolute() else REPO_ROOT / args.out
    try:
        build_site(out_dir)
    except (RuntimeError, FileNotFoundError) as err:
        sys.stderr.write(f"build failed: {err}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
