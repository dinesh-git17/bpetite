# Banned Patterns Reference

This file is loaded during the Phase 4 anti-slop pass. Check the README against every
category below before outputting. One hit is one too many.

---

## Forbidden Words

These words either signal AI prose or carry no real meaning. Remove or replace with
something specific.

**Empty superlatives:**
seamlessly, powerful, robust, intuitive, elegant, comprehensive, cutting-edge,
state-of-the-art, innovative, revolutionary, groundbreaking, next-generation,
world-class, game-changing, best-in-class, blazing, lightning-fast, blazing-fast,
supercharged, effortlessly, painlessly

**Condescending simplicity signals:**
simply, easily, obviously, clearly, just (as in "just run X"), trivially, straightforward
(when used to describe user effort, not technical architecture)

**Marketing verbs with no content:**
leverage, harness, utilize (use "use"), facilitate, empower, amplify, elevate, transform
(as marketing claim), revolutionize, reimagine, redefine

**AI-fingerprint verbs:**
delve, tackle (metaphorically), navigate (metaphorically), embark, foster, cultivate,
showcase (in the opening description), underscore (as emphasis), highlight (as emphasis)

**Hedge words that signal overreach:**
certainly, undoubtedly, undeniably, obviously (repeated from above — it earns two strikes)

---

## Forbidden Phrases

These multi-word patterns appear in almost every AI-generated README. Their presence
alone signals non-human authorship.

**Opening gambits (never use these to start a description):**
- "at its core"
- "under the hood"
- "in today's [anything] world"
- "in the modern [anything] landscape"
- "built for the future"
- "designed with [users] in mind"
- "X that just works"
- "the X you've been waiting for"

**Feature list clichés:**
- "and much more"
- "and more"
- "among other things"
- "a wide range of"
- "a comprehensive suite of"
- "out of the box" (unless it is literally true and specific)
- "batteries included" (overused to meaninglessness)
- "zero configuration" (only acceptable if literally true and demonstrable)
- "production-ready" (only acceptable if backed by specific evidence)
- "drop-in replacement"

**Marketing phrases:**
- "say goodbye to X"
- "never X again"
- "with X, you can finally"
- "take your X to the next level"
- "X made easy"
- "X for humans"
- "built for developers, by developers"
- "where X meets Y" (as a positioning tagline)
- "X, reimagined"

**Structural throat-clearing:**
- "This README covers..."
- "In this document, you will find..."
- "This section explains..."
- "The following sections describe..."
- "Read on to learn..."
- "Let's dive in"
- "Let's get started"

---

## Structural AI Tells

These are patterns at the sentence and paragraph level, not the word level. They are
harder to catch because individual sentences can look fine. Look at the structure.

**The rule of three:**
Three consecutive parallel items — three bullet points in a row, three benefits, three
examples, three anything. AI is trained on writing that uses this device sparingly and
reproduces it indiscriminately. If you have written three parallel items in a row,
collapse to two or expand to a real list with a table.

**Present-participle chains:**
Sentences that pile on "-ing" clauses to simulate depth.
Bad: "...making it easy to query, enabling real-time responses, allowing you to skip
the boilerplate and focus on what matters."
Fix: Stop after the main verb. One clause per sentence.

**Hedging seesaw:**
"While X has Y, it also Z" or "On one hand... on the other hand..."
If this appears in a README, it is usually either unnecessary context or a sign that
the paragraph should be cut entirely.

**Corporate pep talk:**
"We built X because we believe..." or "Our mission is..." in a library or tool README.
Acceptable in a company's open-source project with a genuine community story. Not
acceptable as a substitute for explaining what the software does.

**Inflated present participles used for padding:**
"...reflecting our commitment to quality, showcasing our dedication to developer
experience, enabling teams to..."
These are meaning-free. Cut them.

**Uniform sentence length:**
Read the README aloud. If every sentence takes the same amount of time to say, that is
an AI tell. Vary length deliberately. Short sentences land. Longer sentences can carry
nuance and context when they earn it, but they should not all be the same length as each
other or as their neighbors.

**Symmetric bullet points:**
Every bullet point starting with the same word form (all verbs, all nouns, all gerunds)
and all approximately the same length. This looks organized but reads as machine-generated.
Vary entry points while keeping actual meaning clear.

---

## Punctuation Tells

**Em dashes (—):**
Remove every single one. There are no exceptions. Em dashes are the single strongest
punctuation signal of AI authorship in 2024-2026 text. Use a comma, a period, or
restructure the sentence.

**Exclamation points:**
Maximum one per README. Reserve it for something that is genuinely exciting, not for
enthusiastic prose. "Get started today!" is not an acceptable use.

**Ellipsis for effect (...):**
Do not use ellipsis to create suspense or trailing-off effect in prose. Only use for
actual omission in quoted code.

**Overuse of colons as drama:**
"The result: instant feedback." Once in a README is fine. Multiple times signals a
stylistic tic.

---

## Formatting Patterns

**Badge walls:**
More than 4 badges in the header is a badge wall. Cut to the ones that carry signal for
the reader. "PRs welcome" and "Contributions welcome" badges tell the reader nothing they
didn't already know.

**Emoji in every section header:**
One or two emoji in headers can work as navigation anchors. Every header with an emoji
is visual noise. Either use them consistently and sparingly (one per section for visual
rhythm) or not at all.

**"🚀" "⚡" "✨" for enthusiasm:**
These three in particular signal generic AI README output. If you feel the urge to add
them for excitement, the prose is not doing its job.

**Section count padding:**
"Roadmap", "Changelog", "FAQ", "Acknowledgements", and "Support" sections that exist
because templates include them but contain no real content. Cut them. A stub section is
worse than no section.

**Nested bullet points for simple information:**
If information does not have a genuine parent-child relationship, do not create fake
hierarchy with nested bullets. Prose or a flat list is cleaner.
