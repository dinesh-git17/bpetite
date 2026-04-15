# Repo Information Architecture

Section order is a design decision, not a default. The wrong order produces a README
that has all the right pieces assembled incorrectly. Read the section for your repo type
and follow it exactly — deviating requires a specific reason, not a preference.

---

## Library / Package

A library README is a contract with another developer. The reader's question is always:
"does this do what I need, and can I trust it?" Answer those two things before anything else.

**Section order:**

1. **Header block** (centered: name, one-line tagline, 3-4 badges: version + license + CI)
2. **Minimal usage example** (a code block — the simplest thing someone would write)
   Show this before installation. A reader who sees that the API is clean will install it.
   A reader who sees only installation steps may not.
3. **Installation** (one command: `pip install X` / `npm install X` / `go get X`)
4. **"Why this exists"** (1-3 paragraphs: the problem, why existing solutions fell short,
   what makes this one different. Be specific. "Better performance" is not a reason.)
5. **Features** (table if 5+; short prose or a tight list if fewer)
6. **Extended usage / examples** (2-3 real-world code examples, not toy examples)
7. **Documentation** (link out — if extensive docs exist, the README is the on-ramp, not the docs)
8. **Contributing** (brief; link to CONTRIBUTING.md if it exists)
9. **License** (one line)

**Notes:**

- If the library has a comparison to well-known alternatives, put it after "Why this exists."
  Keep it factual and specific. Do not be disparaging.
- If there is a performance benchmark, it belongs in or near "Why this exists" if it is
  the primary reason to choose this library.
- Do not pad with "Roadmap", "FAQ", or "Acknowledgements" unless they contain real content.

---

## CLI Tool

A CLI README is a reference and a pitch simultaneously. The reader wants to know what
the tool does, see it doing it, and start using it in under 2 minutes. Show before tell.

**Section order:**

1. **Header block** (name, one-line tagline, 2-3 badges: version + license)
2. **Demo GIF** (if one exists — this is the most important thing on the page)
   If no GIF exists, put a code block showing input and output side by side instead.
3. **Installation** (one command per package manager; list the relevant ones)
4. **Quickstart** (the first command a new user runs + what they see)
   This is different from the full usage reference. It answers "how do I get something
   useful out of this in the next 60 seconds?"
5. **Commands / flags reference** (table: command, description, example)
6. **Real-world examples** (2-3 copy-pasteable use cases that actually reflect real use,
   not contrived ones. Include the output.)
7. **Configuration** (if applicable — file format, env vars, precedence rules)
8. **Contributing** (brief)
9. **License**

**Notes:**

- If the tool has shell completion support, mention it in the Installation or Quickstart
  section — it is a usability signal that tells developers this is a polished tool.
- If the tool has a config file format, include a minimal working example, not just
  a reference to all possible keys.
- Avoid the pattern of listing every flag in prose before showing an example. Show
  the example first.

---

## Full-Stack App

A full-stack app README has two jobs: convince someone to try it, and help someone
run it locally. The problem being solved is the hero. Feature lists come after.

**Section order:**

1. **Header block** (logo if one exists + name + live demo badge if app is hosted,
   2-3 badges: tech stack highlight + license)
2. **Demo** (screenshot or GIF, prominent and early — if there is a hosted URL,
   make it obvious here)
3. **What problem this solves** (1-2 paragraphs: the situation, the frustration,
   what this app changes. Write about the problem, not about the app's features.
   Features come next.)
4. **Features** (after the problem is established — 5-8 items, specific and honest.
   Do not list features that exist in every competing tool.)
5. **Tech stack** (brief — one table or short list. Language, framework, database,
   key libraries. Not every dependency.)
6. **Getting started** (three subsections):
   - Prerequisites (what must be installed first)
   - Installation (clone + install + configure)
   - Running locally (the one command, and what to expect)
7. **Environment variables** (table: variable, description, required/optional, example value)
   Only if the app has non-trivial configuration.
8. **Architecture** (optional — a Mermaid diagram if the architecture is non-obvious
   and a contributor would benefit from the overview)
9. **Contributing** (brief)
10. **License**

**Notes:**

- The "What problem this solves" section is where most full-stack app READMEs fail.
  They skip straight to features. Write the problem paragraph first and the reader
  will care about the features when they arrive.
- If the app has a hosted demo, put the URL in at least two places: the badge block
  and the "What problem this solves" section. Do not make the reader hunt for it.
- Environment variable tables should include example values, not just descriptions.
  `.env.example` as a reference is fine but the table in the README is more scannable.

---

## Portfolio Project

A portfolio README has one reader: a senior engineer deciding whether to explore further.
That reader is skeptical, time-constrained, and pattern-matches fast. Technical depth
signals credibility. Generic praise signals the opposite.

**Section order:**

1. **Header block** (name + live demo link if applicable, 2 badges: primary tech + license)
2. **What it is and why it exists** (2-3 sentences, honest. What the project does,
   what motivated it, why this was worth building. Not "I built this to learn X" —
   that's fine if it's true but it should not be the lead.)
3. **Demo** (live URL, screenshot, or GIF — wherever it fits naturally after the intro)
4. **The interesting technical part** (the section that makes a senior engineer stop
   scrolling. What was hard? What did you figure out? What would not have been obvious
   without building it? Be specific. One paragraph is enough if it is the right one.)
5. **Stack** (brief list — language, framework, key libraries, deployment)
6. **Running locally** (minimal — assumes some competence. Clone, install, run.
   Do not hand-hold through installing Node or Python.)
7. **Design decisions** (optional but often the most interesting section for a portfolio
   project. One to three decisions, each with a "what I chose" and "why, honestly."
   This is where intellectual honesty lives — include what didn't work if relevant.)
8. **License**

**Notes:**

- The "interesting technical part" is the section most portfolio READMEs are missing.
  It is what separates a repo that says "I can build things" from one that says
  "I can think about problems." Dinesh should be specific here: not "implemented
  real-time features" but "used SSE instead of WebSockets because the traffic pattern
  was write-heavy from server to client, which made WebSocket's bidirectionality overhead
  not worth the connection cost."
- The "Design decisions" section should not be used as a victory lap. If a decision
  turned out to be wrong, saying so is more credible than pretending it was always right.
- Do not include a "What I learned" section framed as a learning diary. Reframe it
  as design decisions or technical notes. "What I learned" reads junior; "what I chose
  and why" reads senior.
- Portfolio projects do not need a "Contributing" section unless the project genuinely
  welcomes contributors (which is rare for portfolio work).
