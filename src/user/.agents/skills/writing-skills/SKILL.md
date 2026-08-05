---
name: writing-skills
description: Use when creating a new skill, editing an existing skill, or verifying a skill works before deploying it. Apply whenever the user mentions skills, SKILL.md, skill authoring, skill testing, skill triggering accuracy, capturing a workflow as a reusable skill, or wants to know whether a skill is ready to ship — even if they don't explicitly say "skill" and just describe wanting to "package this up" or "make this reusable."
admission:
  provides: Mechanism for creating, editing and verifying skills for agents.
  cost: Unknown
  remove_when: Agents prove they can craft their own skills with high quality.
---

<!--
Sources (amalgam):
  - Source: skills/writing-skills/
    Upstream: https://github.com/obra/superpowers @ f2cbfbefebbfef77321e4c9abc9e949826bea9d7 (v5.1.0)
  - Source: skills/skill-creator/
    Upstream: https://github.com/anthropics/skills @ f458cee31a7577a47ba0c9a101976fa599385174
    (development continues at https://github.com/anthropics/claude-plugins-official;
    the pinned repository and commit both remain reachable, and content was
    verified byte-identical at the 2026-07-17 repo-move refresh)
Last sync: 2026-05-17
Drift policy: accept-periodic-resync. The merged SKILL.md is the authoritative
copy and may diverge from either upstream. To inspect drift, clone each
upstream at the SHA above and diff that against this copy. On a resync, bump
both SHAs and the date in the same change.

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
Internal cross-references use bare-name skill conventions (e.g., `test-driven-development`).
If a cross-reference dangles in a deployment, verify the skill exists in your installation.
-->

# Writing Skills

## Overview

**Writing skills IS Test-Driven Development applied to process documentation.**

**Core principle:** If you didn't watch an agent fail without the skill, you
don't know if the skill teaches the right thing. If you didn't watch the
description compete with realistic near-miss queries, you don't know if it
will trigger when it should.

**REQUIRED BACKGROUND:** You MUST understand `test-driven-development` before
using this skill. That skill defines the RED-GREEN-REFACTOR cycle; this one
adapts it to documentation.

A **skill** is a reference guide for proven techniques, patterns, or tools —
reusable methods a future agent can find and apply. A skill is NOT a narrative
about how you solved a problem once.

## Three Skill Types and the Register Split

The single most important design decision is what *kind* of skill you are
writing. The type drives both the **register** (how MUST-y the prose is) and
the **test approach**.

| Type | Examples | Register | Test approach |
|------|----------|----------|---------------|
| **Discipline** | rules you must obey under pressure | Hard MUSTs, Iron Law, "no exceptions," rationalization tables, red-flag lists | Pressure scenarios combining time + sunk-cost + authority |
| **Technique** | how-to guides for a method | Soft, explain-the-why, theory-of-mind framing, examples beat MUSTs | Application scenarios on a new problem |
| **Reference** | API docs, schemas, library guides | Neutral, scan-optimized tables, no admonitions | Retrieval scenarios |

**Why the split matters.** Discipline skills exist because the agent will
rationalize, and soft prose loses to time pressure — the MUSTs *are* the
skill. Technique skills exist because the agent doesn't know the method, and
hard MUSTs make it rigid where explanation makes it capable. Reference skills
just need to be scannable.

**Pick the type first, then write to the register.** Mixing registers within
one skill is a smell — usually it means the skill is doing two jobs and should
be split.

**One exception: mechanical constraints carry MUSTs regardless of type.** When
the runtime enforces a rule (depth-1 discovery, `name:` matching the folder,
1024-char frontmatter), use a MUST even in a technique skill. The register
split governs *judgment-call* prose, not constraints the host rejects anyway.

## Progressive Disclosure — the Budget You Are Writing Against

Three loading levels, and the cost of each is why the split exists:

1. **Metadata** (frontmatter `name` + `description`) — always in context,
   every session, for every installed skill. The description alone decides
   whether the body ever loads.
2. **SKILL.md body** — loaded when the skill triggers, and charged against a
   deployed per-skill token budget. Keep it to what the agent needs in order
   to *decide* how to proceed.
3. **Bundled resources** (`references/`, `scripts/`, `assets/`) — loaded on
   demand, unbudgeted. Scripts can execute without their source entering
   context at all.

So heavy reference, full example sets, and step-by-step checklists belong in
`references/`; principles and decision tables stay inline. When a body
outgrows its budget, move sections out **verbatim** and leave a pointer —
cutting content to fit is how a skill quietly stops teaching what it used to.

**Depth-1 only.** Every immediate subdirectory of the skills root is exactly
one skill. Skills MUST NOT be nested under organizational subfolders — all
four major runtimes (Claude Code, Codex CLI, Gemini CLI, OpenCode) discover
skills one level deep.

Layout, frontmatter fields, body-section conventions, cross-referencing
markers, and the two content constraints are in `references/anatomy.md`.

## Writing the Description

The description does two jobs that look contradictory: it must make the agent
load the body when relevant, and it must not let the agent act on the
description alone. These reconcile into one rule:

> **Be pushy about WHEN, never about WHAT or HOW.**

```yaml
# ❌ BAD — summarizes workflow; the agent follows this and skips the body
description: Use when executing plans — dispatches subagent per task with code review between tasks

# ✅ GOOD — trigger-dense, pushy, process-free
description: Use when tests have race conditions, timing dependencies, or pass/fail inconsistently. Apply whenever the user mentions flakiness, hangs, timeouts, zombie processes, or "works locally but fails in CI" — even if they describe the symptom without naming async/timing as the cause.
```

Full guidance — the pushy and process-free checklists, keyword coverage,
naming, and the complete example set — is in `references/descriptions.md`.

## The Iron Law

```
NO SKILL WITHOUT A FAILING TEST FIRST
```

This applies to NEW skills AND EDITS to existing skills.

Wrote skill before testing? Delete it. Start over. Edited without testing?
Same violation.

**No exceptions:** not for "simple additions," not for "just adding a
section," not for "documentation updates." Don't keep untested changes as
"reference." Don't "adapt" while running tests. Delete means delete.

**Violating the letter of the rules is violating the spirit of the rules.**

This applies in full to **discipline-type** skills. For technique and
reference skills the spirit still applies — verify the skill teaches what you
think it teaches — but the test format is application or retrieval, not
pressure compliance.

## RED-GREEN-REFACTOR for Skills

| TDD Concept | Skill Creation |
|-------------|----------------|
| Test case | Pressure scenario, application scenario, or trigger-eval query |
| Production code | SKILL.md |
| Test fails (RED) | Agent violates rule, fumbles technique, or skill undertriggers |
| Test passes (GREEN) | Agent complies, applies correctly, or triggers reliably |
| Refactor | Close loopholes, tighten examples, tune description |

**RED** — run the scenario WITHOUT the skill (or with the OLD version).
Capture verbatim: what choices the agent made, what rationalizations it used,
which queries failed to trigger.

**GREEN** — address the specific failures observed in RED. Don't add content
for hypothetical cases that never came up. Re-run WITH the skill.

**REFACTOR** — the agent will find new rationalizations and near-miss
failures. Add explicit counters. Re-test until bulletproof.

## Bundled References

| File | Read when |
|------|-----------|
| `checklist.md` | **Before shipping — always** |
| `anatomy.md` | Laying out a skill; frontmatter; cross-references |
| `descriptions.md` | Writing or tuning the description |
| `testing-methodology.md` | Designing scenarios; the trigger-eval loop |
| `testing-skills-with-subagents.md` | Running the full pressure-subagent method |
| `bulletproofing.md` | Hardening a discipline skill |
| `anti-patterns.md` | Reviewing; adding a flowchart or example |
| `anthropic-best-practices.md` | Anthropic's longer-form guidance |
| `persuasion-principles.md` | Why discipline prose sticks |
| `schemas.md` | Eval or grading JSON |
| `graphviz-conventions.dot` | Flowchart style |

## The Bottom Line

Creating skills IS TDD for process documentation. Same Iron Law: no skill
without a failing test first. Same cycle: RED → GREEN → REFACTOR. After
writing ANY skill you MUST STOP and work `references/checklist.md` before
moving on — deploying untested skills is deploying untested code.
