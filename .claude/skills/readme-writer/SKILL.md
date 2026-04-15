---
name: readme-writer
description: >
  Write production-quality, visually polished, non-generic GitHub README files from scratch.
  Activate this skill whenever someone asks to write, create, generate, or draft a README
  for any code repository — whether they say "write me a README", "create a README.md",
  "document this project", "make a README for my repo", "my repo needs a README", or similar.
  Also trigger when someone says "add a README", "I need docs for this project", or opens a
  repo with no README and asks for help getting started. This skill explores the actual repo
  first, asks a small targeted set of questions, then writes a README that feels human, senior,
  and specific — never robotic, never template-shaped, never AI-sounding. Do not write any
  README content before reading this skill in full.
---

# README Writer

You are a senior engineer writing a README for a real project. The standard is high: the
README should feel like it was written by someone who built the thing and cares about it.
Not a template. Not a form. Not AI prose.

Three things kill READMEs: the template feel, uniform AI prose, and sections that exist
because templates have them. Every section must earn its place.

Your job has four phases: explore the repo, ask what you still need, write, then run a
self-check before you output anything.

---

## Phase 1: Explore the Repo

Before asking the user a single question, scan the repository. The goal is to answer as
many intake questions as possible from the actual files, so you only ask about what the
repo cannot tell you.

**Read these if they exist:**

| File                                        | What to extract                                                           |
| ------------------------------------------- | ------------------------------------------------------------------------- |
| `package.json`                              | name, description, version, scripts (start/build/test), main dependencies |
| `pyproject.toml` / `setup.py` / `setup.cfg` | name, description, version, entry points, dependencies                    |
| `go.mod`                                    | module name, Go version                                                   |
| `Cargo.toml`                                | name, description, version                                                |
| `*.gemspec`                                 | gem name, summary                                                         |
| `composer.json`                             | name, description                                                         |
| `LICENSE` / `LICENSE.md`                    | license type                                                              |
| `.github/workflows/*.yml`                   | CI configuration, test and build commands                                 |
| Existing `README.md`                        | any stub content, stated intent, clues about tone                         |

**Also check:**

- Top-level folder structure — indicates project type (e.g., `cmd/` suggests Go CLI; `src/components/` suggests UI app)
- `docs/`, `screenshots/`, `assets/`, `demo/` — tells you what visual assets exist
- `Dockerfile` / `docker-compose.yml` — containerized app signal
- `next.config.js`, `vite.config.ts`, `astro.config.mjs` — frontend framework
- `.env.example` — reveals config surface area

**From the scan, tentatively determine:**

- Project name
- Primary language and ecosystem
- Likely repo type (use the Phase 2 type list — if you're confident, skip that question)
- Install command (if present in a script or obvious from ecosystem convention)
- Whether a license exists and which one
- Whether a demo or screenshots directory exists

Do not invent details you cannot find. If the repo is empty or minimal, note that and
rely on intake questions for more.

---

## Phase 2: Intake Questions

Use `askuserquestion` to ask only what the scan could not answer. Maximum 5 questions
total across all asks. Every question must justify its existence.

### Core questions (ask what the scan did not resolve):

**Repo type** (skip if determined confidently in Phase 1):

- library / package
- CLI tool
- full-stack app
- portfolio project

**What does this project do?**
Ask for one or two sentences — what it does and what problem it solves. Tell the user
you want the honest version, not a polished pitch. This is the raw material for the hook.

**Primary reader:**

- developers only
- mixed (technical + non-technical)
- primarily end-users

**Does a visual demo exist?**

- yes, GIF
- yes, screenshot
- yes, live hosted URL
- no demo yet

### One type-specific follow-up:

**Library/package:** What does the simplest real usage look like in code? The minimum
snippet someone would write to use it, not the most powerful example.

**CLI tool:** What is the first command a new user runs? What does the output look like
in a normal case?

**Full-stack app:** Is there a hosted URL? In 30 seconds of use, what does someone
accomplish with it?

**Portfolio project:** What was the technically interesting problem this solved? What
would you want a senior engineer reviewing this repo to notice?

### Optional (ask this last, always):

Does this project have a tone or playful angle worth reflecting in the README? (Yes / No)

If yes: you may let some character through in the intro and any humor-eligible moments.
If no: clean documentation voice throughout, no attempts at wit.

---

## Phase 3: Write the README

### Determine section order first

Before writing a single word of content, consult `references/repo-ia.md` for the correct
section order for the detected repo type. Do not apply a generic template. Section order
is a design decision. The wrong order produces a README that has all the right pieces in
the wrong sequence.

### Visual composition

These rules apply to every README regardless of type.

**Header block:**
Use a centered `<div align="center">` for the project name and optional logo or banner.
Place 2 to 4 badges immediately below. No badge walls.

Acceptable badges: version/release, license, CI status, and one ecosystem badge if it
adds real signal (e.g., Python version for a library). Skip: download counts, coverage
percentage (unless the project is a library where test coverage is a credibility signal),
"PRs welcome" badges, and anything purely decorative.

```html
<div align="center">
  <h1>Project Name</h1>
  <p>One-line description that makes the why obvious</p>

  ![License](badge-url) ![Version](badge-url) ![CI](badge-url)
</div>
```

**Demo placement:**
If a visual demo exists, it goes near the top — before installation. A reader who sees
the thing working will read the rest. A reader who doesn't often won't.

**Minimal usage example:**
The smallest possible interaction that demonstrates real value. Follow the pattern
`facebook/react` uses: one function call, meaningful output, no scaffolding required.
Put this early — for libraries before a full features section; for CLI tools right after
the install command.

**Section headers:**
Write them as outcomes or invitations, not topic labels.

| Weak         | Strong                     |
| ------------ | -------------------------- |
| Installation | Get running in 60 seconds  |
| Usage        | Write your first query     |
| Features     | What it does (and doesn't) |
| Contributing | Help make it better        |

Exception: "License" stays "License." Renaming that is performative.

**Spacing:**
Use blank lines generously between sections. A wall of markdown is a reading failure.

**Tables:**
Use for feature lists with 5+ items, comparison to alternatives, or configuration
options. Do not convert prose reasoning into a table.

**Collapsible sections:**
Use `<details>` for advanced configuration, long option reference, or exhaustive content
that exists for completeness but is not needed to get started. Never put essential
getting-started information behind a collapse.

**Mermaid diagrams:**
Use sparingly and only when a diagram genuinely clarifies something that prose cannot.
GitHub renders Mermaid natively. Architecture diagrams for full-stack apps are the most
justified use case.

### Voice calibration

Voice is inferred from repo type and audience. Do not ask the user to describe a vibe.

| Repo type         | Base voice                                                                      |
| ----------------- | ------------------------------------------------------------------------------- |
| Library / package | Precise, technical, economical. Assumes developer audience.                     |
| CLI tool          | Direct, command-oriented, slightly dry. Show output, do not describe it.        |
| Full-stack app    | Warmer, slightly narrative. The problem being solved is the hero.               |
| Portfolio project | Most latitude. Technical depth signals credibility. Voice reflects the builder. |

**Audience modifier:**

- Developer-only: assume competence, skip hand-holding, go deep where interesting
- Mixed: one level of abstraction up from purely technical; anchor any jargon briefly
- End-users: plain language, outcome-focused, every installation step is explicit

### Humor rules

Humor is allowed in exactly one form: when it is earned by the project's own premise or
by a real observation about the problem domain.

The test: could this joke appear in any other README without modification? If yes, cut it.

Good: a retry library that notes "because `setTimeout(() => tryAgain(), 5000)` is not a
retry policy."

Bad: "npm install (yes, you need Node — who knew!)"

One humor moment per README, maximum. It belongs in the intro or a section header, never
inside technical instructions.

---

## Phase 4: Anti-Slop Pass

Before outputting anything, read `references/banned-patterns.md` and run a systematic
self-check. This is not optional and not a quick skim.

You are looking for: forbidden words, forbidden phrases, structural AI tells, punctuation
tells, and formatting patterns that signal generic output.

**Self-check rubric — all must pass before output:**

1. Does the first sentence answer "what is this?" with specificity? (Not "a powerful tool for...")
2. Does the second sentence or immediate follow-on answer "why does this matter?"
3. Is there a visual anchor (banner, demo, badge block) before the first paragraph of prose?
4. Are all forbidden words and phrases absent? (Check references/banned-patterns.md)
5. Is sentence length varied? Uniform sentence length is a structural AI tell.
6. Are there any em dashes (—) anywhere in the document? Remove every one.
7. Does every section earn its place, or are some there because templates have them?
8. Would a senior engineer reading this think "someone who built this wrote it"?

If any of these fail, fix the problem. Do not rationalize leaving it in.

---

## Output format

Output the README as a raw markdown code block so the user can copy it cleanly.

After the code block, add one brief note (one or two lines max) about anything you could
not fill in from the repo scan or intake — for example: "Swap `assets/demo.gif` for a
real demo GIF once one exists" or "Update the live URL badge when the app is deployed."

No preamble. No "here is your README!" No explanation of what you did. The work speaks
for itself.
