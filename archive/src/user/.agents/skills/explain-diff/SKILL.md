---
name: explain-diff
description: Use when the user wants a rich, engaging explanation of a code change — a PR, diff, branch, commit range, or "what changed here." Triggers on "explain this PR", "walk me through this change/branch/diff", "help me understand what this does", "write this up for the team", "onboard someone to this change", or asking for a shareable/interactive writeup of a change. Produces a single self-contained HTML explainer. Not for line-by-line code review.
model: sonnet
effort: medium
---

# Explain Diff

## Overview

Produce a rich, fun, interactive **explanation** of a code change, aimed at
helping a reader *understand* it — not review it line by line. The reader should
come away knowing: what the change does, why it was made, how it fits the larger
codebase, how it works, how to use it, and what risks it introduces.

Output is one self-contained HTML file. Consistency of look across explainers
comes from the bundled `assets/` — inline them rather than restyling from scratch.

## When to use

- The user asks to explain / walk through / write up a PR, diff, branch, or commit range.
- Onboarding someone to a change, or sharing an interactive writeup.

**Not for:** line-by-line code review, approve/reject verdicts, or a plain-text summary.

## Steps

1. **Explore before writing.** Read the diff *and* the surrounding code — enough to
   place the change in its bigger picture. You cannot write a good Background or
   Intuition section from the diff alone.
2. **Resolve the persona** (see Tone below) — decide whose voice narrates *before* you
   start writing, so the whole page reads in one consistent voice.
3. **Inline the theme.** Read `assets/theme.css` and `assets/quiz.js` and paste them
   verbatim into a `<style>` and `<script>` block. Read `assets/palette.md` for the
   class vocabulary. Compose the page from those classes; do **not** hardcode hex
   colors or invent parallel styles — that is what keeps every explainer consistent.
4. **Write the four sections** (below), using the documented callouts, diagrams, and
   quiz markup.
5. **Save** to the destination (see Format — user-named path or the dated default),
   then run the self-check.
6. **Open it** — unless the user asked you not to, open the finished file in the
   default viewer with the platform opener, passing the saved path as the argument
   (quote it if it may contain spaces): `open "<file>"` (macOS), `xdg-open "<file>"`
   (Linux), or `start "" "<file>"` (Windows — the `""` is the window-title arg, so the
   path must follow it). Suppress on any
   "don't open / no auto-open / just save" instruction. Either way, print the final
   path so the reader can find it.

## Sections

- **Background** — the existing system this change touches. Because you don't know
  how much the reader knows, give a deep beginner background in a collapsed
  `<details>` (skippable), then a narrow background directly relevant to the change.
- **Intuition** — the core idea, the essence over the details. Concrete toy-data
  examples. Lean on diagrams.
- **Code** — a high-level walkthrough of the changes, grouped/ordered so it reads as
  a story, not a file list.
- **Quiz** — five medium-difficulty multiple-choice questions that require actually
  understanding the change (not gotchas), each with feedback on click. Every question
  has exactly four options: two plausible-but-wrong distractors, one correct answer,
  and one false comic foil marked `data-comic="true"`. The comic foil's **visible
  text** must be immediately and factually incompatible with the change, not merely a
  plausible misconception with a snarky suffix. Write both that option and its
  feedback in the resolved persona's cadence, references, and attitude. The template
  in `palette.md` shows the required markup; vary option order across questions so the
  template's position does not become an answer cue.

## Tone

Funny, snarky, engaging. Playfully sarcastic/condescending is fine. The *specific*
voice is not hardcoded — resolve a persona, then narrate the whole page in it.

**Resolve the persona — first match wins:**

1. **Named** — if the invocation explicitly names one of the bundled personas (e.g.
   `--persona=glados`, or "explain this as GLaDOS"), use that one. An explicit ask
   beats everything.
2. **Active** — otherwise, if you already have an active persona / voice directive in
   your context, reuse it. (This is a soft self-check — there's no mechanical signal to
   query, so if no such directive is present, fall through.)
3. **Random** — otherwise pick one at random from the bundled assets:

   ```bash
   ls assets/personas/*.yaml | sort -R | head -1
   ```

   No git dependency, works in any directory, and picks fresh each run (`sort -R`
   over `shuf` — `shuf` isn't on stock macOS).

Once resolved, read that persona's YAML and adopt its `theme`, `personality_traits`,
and `tone_traits`; draw flavor from its `snarky_examples`. Tell the reader up front
whose voice they're getting and why (e.g. "No persona named — rolled GLaDOS."). Stay
in that voice for the entire page — one narrator, start to finish.

## Format

- **One self-contained HTML file** — all CSS and JS inlined (from `assets/`), no
  external requests. One long page with section headers and a `.toc` table of
  contents. No tabs for top-level structure. Responsive (theme.css handles it).
- **Save location:** if the user named a destination (a directory or a full path),
  honor it — write there, keeping the `YYYY-MM-DD-explanation-<slug>.html` filename
  when they gave only a directory. Otherwise **default** to a global place outside the
  code repo, filename starting with today's date as `YYYY-MM-DD-`. Example:
  `/tmp/2026-01-12-explanation-<slug>.html`. Get today's date from the environment;
  don't guess it.
- **Diagrams:** pick a small number of reusable diagram families and reuse them.
  Useful kinds: a simplified app-UI mock for UI changes (`.uimock`), a data-flow /
  component system diagram with example data (`.flow` + `.node` + `.data-tag`),
  and simple flow/sequence diagrams highlighting the changed step (`.node.hot`).
  **HTML diagrams only — never ASCII art.** Lists of things use HTML lists.
- **Callouts** (`.callout` note/key/warn/def) for key concepts, definitions, and edge cases.

## Self-check before you're done

- Every `<pre>`/code block preserves newlines. `theme.css` sets `white-space: pre`
  on `<pre>`, but if you used a custom `div` for a code block it **must** carry
  `white-space: pre-wrap` or the browser collapses it to one line. Scan each block.
- `theme.css` and `quiz.js` are inlined verbatim; no external `<link>`/`<script src>`.
- TOC anchors match the section `id`s.
- Each quiz question has exactly four `.opt` buttons: two plausible false distractors,
  one `data-correct="true"` option, and one false `data-comic="true"` comic foil,
  plus a `.feedback` div.
- Read every comic foil before saving: its visible text is plainly impossible for the
  change, and both it and its feedback sound like the resolved persona. A generic joke
  pasted onto an otherwise plausible answer does not qualify.
- A persona was resolved (named / active / random), named to the reader up front, and
  held consistently across every section — no voice drift, no leftover Marvin default.
