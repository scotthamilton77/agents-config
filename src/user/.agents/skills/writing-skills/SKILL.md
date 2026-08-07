---
name: writing-skills
description: Use when creating or editing a skill, verifying a skill triggers before deploying it, or authoring or improving an AGENTS.md or CLAUDE.md. Apply whenever the user mentions skills, SKILL.md, skill authoring, or skill testing; whenever agent instructions, project rules, or a CLAUDE.md are being written, trimmed, or reorganised; and whenever a document an agent reads is too long, gets ignored, or fires at the wrong time — even if they don't say "skill" and just describe wanting to "package this up", "make this reusable", or "tighten up the agent instructions".
admission:
  provides: A method for authoring any document an agent reads — a skill, or an
    AGENTS.md/CLAUDE.md — producing a trigger tested against near-misses, a body
    sized to its budget, and material disclosed to references by branch, instead
    of prose written by imitation of whatever skill the author read last.
  cost: ~1.9k tokens on invoke plus an always-on description, and a RED baseline
    run before every skill edit, which is slower than editing the prose directly.
  remove_when: Agents author skills and instruction files that trigger accurately
    and stay within budget without being told the method.
---

<!--
Amalgam of three upstreams, one Source/Upstream pair each. Keep every key at the
start of its own line: the installer recognises a provenance header by matching
`Source:`/`Upstream:` there, so folding these into bullets or prose would stop
this block being stripped and ship these paths into every downstream install.

  Source: skills/writing-skills/
  Upstream: https://github.com/obra/superpowers @ f2cbfbefebbfef77321e4c9abc9e949826bea9d7 (v5.1.0)

  Source: skills/skill-creator/
  Upstream: https://github.com/anthropics/skills @ f458cee31a7577a47ba0c9a101976fa599385174
  (development continues at https://github.com/anthropics/claude-plugins-official;
  the pinned repository and commit both remain reachable, and content was
  verified byte-identical at the 2026-07-17 repo-move refresh)

  Source: skills/productivity/writing-for-agents/
  Upstream: https://github.com/mattpocock/skills @ 4aaccb58d40559d7e3c59a029b2290ae5ba538de
  (all three files in that directory — SKILL.md, SKILL-MECHANICS.md and
  agents/openai.yaml — were verified byte-identical to this commit's blobs by
  hash. SKILL.md and SKILL-MECHANICS.md reached this content two commits
  earlier at f054defc, but 4aaccb58 is the first commit at which the whole
  source directory reproduces, so it is the pin. Only the first two were
  grafted; agents/openai.yaml is upstream-specific and was not taken.)
Last sync: 2026-08-07
Drift policy: selective-amalgamation. The merged SKILL.md is the authoritative
copy and diverges from every upstream by construction — specific patterns were
lifted, not whole files, so a resync would revert the graft. To inspect drift,
clone each upstream at the SHA above and diff that against this copy. On a
resync, bump the SHAs and the date in the same change.

Bundled resources (scripts/, references/, examples/) were byte-identical
copies of the upstream artifacts at the SHAs above at initial import.
Documented divergences since:
  - scripts/render-graphs.js — patched to exit non-zero on render failure
    (upstream bug; not yet fixed in the source repo). Later given a
    `module.exports` and a `require.main === module` guard so its pure
    helpers are reachable from scripts/render-graphs_test.js.
  - references/anthropic-best-practices.md, references/persuasion-principles.md,
    references/testing-skills-with-subagents.md, references/schemas.md — each
    gained a "## Contents" TOC near the top per the project skill primer's
    >100-line requirement; existing content preserved.
  - references/testing-skills-with-subagents.md — line "Add symptoms of ABOUT
    to violate." repaired to "Add symptoms of when you're ABOUT to violate
    the rule." (upstream truncation typo).
  - This SKILL.md body was 2.9x over the deployed skill-body token cap. Six
    sections moved verbatim into project-added references — descriptions.md,
    testing-methodology.md, bulletproofing.md, checklist.md, anatomy.md,
    anti-patterns.md — leaving inline only what an agent needs in order to
    DECIDE how to proceed. Content preserved, not cut; the description is
    byte-unchanged, so triggering behaviour is unaffected.
  - references/writing-for-agents.md — the third upstream's SKILL.md and
    SKILL-MECHANICS.md, grafted as theory. Reordered into one file, its
    pointers redirected here, and its "completion criterion" renamed
    "completion bound" to keep it distinct from a review's acceptance
    criteria. Its steps/reference split, invocation axis and pruning levers
    are the parts that reshaped this body.
Internal cross-references use bare-name skill conventions (e.g., `test-driven-development`).
If a cross-reference dangles in a deployment, verify the skill exists in your installation.
-->

# Writing Skills and Agent Instruction Files

## Scope

One method, two documents: a **skill**, and an **`AGENTS.md` / `CLAUDE.md`** — plus
any doc either points at. The packaging differs; the writing does not. A skill is a
reference guide for reusable methods a future agent can find and apply, not a
narrative about how you solved a problem once.

**Core principle:** a document you didn't watch an agent work without is one you
don't know teaches the right thing; a pointer you didn't watch compete against
realistic near-miss queries is one you don't know will be read.

**Read `references/writing-for-agents.md`** when a rule below doesn't decide your
case: you can't tell what to inline and what to disclose, a document is followed
unreliably or ignored, a pointer misfires, or you are cutting a document down and
need to know what is safe to cut.

## Context pointers — the wording is the trigger

A **context pointer** names out-of-context material and encodes the condition for
reaching it. A skill's `description` is one; a line in `AGENTS.md` naming a doc is
the same object. **The pointer's wording, not its target, decides whether the agent
reaches the material.** A must-have target behind a weak pointer is a variance bug
— sharpen the wording first, and inline the material only if that fails.

One rule governs every pointer:

> **Be pushy about WHEN, never about WHAT or HOW.**

A description summarizing workflow gets acted on in place of the body; one piling up
conditions loads the body at the right moment and does nothing else.

A pointer lists the **branches** that should trigger it — one trigger per branch,
front-loading the word that does the triggering. Synonyms renaming a single branch
are one branch written twice. An always-loaded pointer is charged on every turn, so
it earns harder pruning than the body it guards.

Worked examples, checklists, keyword coverage and naming are in
`references/descriptions.md`.

## What to inline and what to disclose

Two budgets are in play. **Context load** is what always-loaded material costs the
agent every turn. **Cognitive load** is what the human pays to remember which
documents exist — not a cost to minimise, but the price of human agency.

A skill spends them across three loading levels: **metadata** (`name` +
`description`) sits in context every session and decides whether anything else
loads; the **body** loads on trigger, against a deployed per-skill token budget;
**bundled resources** (`references/`, `scripts/`, `assets/`) load on demand,
unbudgeted. Hold the body to what the agent needs in order to *decide* how to
proceed.

**Branching is the disclosure test: inline what every branch needs, push behind a
pointer what only some branches reach.** Progressive disclosure is not primarily a
token optimisation — it is how the top of the document stays legible.

**Disclosing is not pruning.** Over budget, move sections out *verbatim* behind a
pointer: the content travels, nothing is lost. Prune only lines failing on their own
merits — a no-op the model already obeys, a duplicate, a stale line. Cutting content
to fit a budget is how a skill quietly stops teaching what it used to.

**Depth-1 only.** Every immediate subdirectory of the skills root is exactly one
skill; skills MUST NOT nest under organizational subfolders. All four major runtimes
(Claude Code, Codex CLI, Gemini CLI, OpenCode) discover one level deep and no more.

Layout, frontmatter fields, body sections and cross-reference markers are in
`references/anatomy.md`.

## Invocation — decide this before writing the description

Every skill is **model-invoked** or **user-invoked**, and the choice trades the two
loads against each other.

| | Model-invoked | User-invoked |
|---|---|---|
| Reachable by | the agent, other skills, and you | you only, by name |
| Context load | its description, permanently | none |
| `description` | model-facing, carries the trigger branches | human-facing one-liner |
| Mechanics | omit `disable-model-invocation` | set it `true`, where the host supports it |

**The rule: choose model-invoked only when the agent must reach the skill on its
own, or another skill must. Otherwise make it user-invoked and pay no context
load.** A description only ever *adds* agent discovery — it never removes your
reach — so the question is never "do I want to type its name", only "must something
other than me find this".

## Three document types and the register split

The type drives both the **register** (how MUST-y the prose is) and the test
approach — pressure scenarios, application scenarios or retrieval scenarios
respectively, laid out under those names in `references/testing-methodology.md`.

| Type | Register |
|------|----------|
| **Discipline** — obeyed under pressure | Hard MUSTs, Iron Law, "no exceptions", rationalization tables, red flags |
| **Technique** — a method the agent lacks | Explain the why; examples beat MUSTs |
| **Reference** — looked up | Neutral, scannable tables, no admonitions |

**Why the split matters.** Discipline documents exist because the agent will
rationalize and soft prose loses to time pressure — the MUSTs *are* the document.
Technique documents exist because the agent lacks the method, and hard MUSTs make it
rigid where explanation makes it capable.

**Pick the type first, then write to the register.** Mixed registers in one document
usually mean it is doing two jobs and should be split.

**Mechanical constraints carry MUSTs regardless of type.** Where the runtime enforces
a rule (depth-1 discovery, `name:` matching the folder, the 1024-char frontmatter
limit), use a MUST even in a technique document: the register split governs
*judgment-call* prose, not constraints the host rejects anyway.

## The Iron Law

```
NO SKILL WITHOUT A FAILING TEST FIRST
```

NEW skills AND EDITS to existing ones — and an instruction file is no exception.
Wrote it before testing? Delete it, start over. Edited without testing? Same
violation.

**No exceptions:** not "simple additions", not "just adding a section", not
"documentation updates". Don't keep untested changes as "reference". Don't "adapt"
while running tests. Delete means delete.

**Violating the letter of the rules is violating the spirit of the rules.**

This binds **discipline** documents in full. For technique and reference the spirit
still applies — verify the document teaches what you think it teaches — but the test
format is application or retrieval, not pressure compliance.

The cycle is `test-driven-development` applied to documentation. **RED** runs the
scenario WITHOUT the document, or with the OLD version, capturing verbatim what the
agent chose and which queries missed; **GREEN** addresses only those failures;
**REFACTOR** counters the rationalizations and near-misses that testing then
surfaces. Scenario design is in `references/testing-methodology.md`.

After writing ANY document covered here you MUST STOP and work
`references/checklist.md` before moving on. Deploying an untested skill is deploying
untested code.

## Bundled references

| File | Read when |
|------|-----------|
| `checklist.md` | **Before shipping — always** |
| `writing-for-agents.md` | An inline-or-disclose call; a misfiring pointer; trimming |
| `anatomy.md` | Layout; frontmatter; cross-references |
| `descriptions.md` | Writing or tuning a description |
| `testing-methodology.md` | Scenario design; the trigger-eval loop |
| `testing-skills-with-subagents.md` | The full pressure-subagent method |
| `bulletproofing.md` | Hardening a discipline skill |
| `anti-patterns.md` | Reviewing; adding a flowchart or example |
| `anthropic-best-practices.md` | Anthropic's longer-form guidance |
| `persuasion-principles.md` | Why discipline prose sticks |
| `schemas.md` | Eval or grading JSON |
| `graphviz-conventions.dot` | Flowchart style |
