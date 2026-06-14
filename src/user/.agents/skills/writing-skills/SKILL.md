---
name: writing-skills
description: Use when creating a new skill, editing an existing skill, or verifying a skill works before deploying it. Apply whenever the user mentions skills, SKILL.md, skill authoring, skill testing, skill triggering accuracy, capturing a workflow as a reusable skill, or wants to know whether a skill is ready to ship — even if they don't explicitly say "skill" and just describe wanting to "package this up" or "make this reusable."
---

<!--
Sources (amalgam):
  - oss-snapshots/superpowers/writing-skills/
    Upstream: https://github.com/obra/superpowers @ f2cbfbefebbfef77321e4c9abc9e949826bea9d7 (v5.1.0)
  - oss-snapshots/anthropics/skill-creator/
    Upstream: https://github.com/anthropics/skills @ f458cee31a7577a47ba0c9a101976fa599385174
Last sync: 2026-05-17
Drift policy: accept-periodic-resync. The merged SKILL.md is the authoritative
copy and may diverge from either upstream. To inspect drift, diff against
the snapshot trees above. On a resync, bump both SHAs and the date in the
same change.

Bundled resources (scripts/, references/, examples/) were byte-identical
copies of the upstream artifacts at the SHAs above at initial import.
Documented divergences since:
  - scripts/render-graphs.js — patched to exit non-zero on render failure
    (upstream bug; not yet fixed in the source repo).
  - references/anthropic-best-practices.md, references/persuasion-principles.md,
    references/testing-skills-with-subagents.md, references/schemas.md — each
    gained a "## Contents" TOC near the top per the project skill primer's
    >100-line requirement; existing content preserved.
  - references/testing-skills-with-subagents.md — line "Add symptoms of ABOUT
    to violate." repaired to "Add symptoms of when you're ABOUT to violate
    the rule." (upstream truncation typo).
Internal cross-references use bare-name skill conventions (e.g., `test-driven-development`).
If a cross-reference dangles in a deployment, verify the skill exists in your installation.
-->

# Writing Skills

## Overview

**Writing skills IS Test-Driven Development applied to process documentation.**

You write test cases (pressure scenarios with subagents, plus trigger-eval
queries), watch them fail (baseline behavior, undertriggering, miscompliance),
write the skill (documentation), watch tests pass (agents comply, descriptions
trigger), and refactor (close loopholes, tune the description).

**Core principle:** If you didn't watch an agent fail without the skill, you
don't know if the skill teaches the right thing. If you didn't watch the
description compete with realistic near-miss queries, you don't know if it
will trigger when it should.

**REQUIRED BACKGROUND:** You MUST understand `test-driven-development` before
using this skill. That skill defines the fundamental RED-GREEN-REFACTOR cycle.
This skill adapts TDD to documentation.

## What is a Skill?

A **skill** is a reference guide for proven techniques, patterns, or tools.
Skills help future agents find and apply effective approaches.

**Skills are:** reusable techniques, patterns, tools, reference guides.

**Skills are NOT:** narratives about how you solved a problem once.

## Three Skill Types and the Register Split

The single most important design decision is what *kind* of skill you are
writing. The type drives both the **register** (how MUST-y the prose is) and
the **test approach** (how you verify it works).

| Type | Examples | Register | Test approach |
|------|----------|----------|---------------|
| **Discipline** | `test-driven-development`, `verify-checklist` — rules you must obey under pressure | Hard MUSTs, Iron Law, "no exceptions," explicit rationalization tables, red flags lists | Pressure scenarios with combined time + sunk-cost + authority pressure; agent must comply under stress |
| **Technique** | `grill-with-docs`, `prototype` — how-to guides for a method | Soft, explain-the-why, theory-of-mind framing, examples beat MUSTs | Application scenarios: can the agent use the technique correctly on a new problem? |
| **Reference** | API docs, schemas, library guides | Neutral documentation voice, scan-optimized tables, no admonitions | Retrieval scenarios: can the agent find the right info and apply it? |

**Why the register split matters.** The two upstream sources of this skill
disagree on tone — one says "write Iron Law, no exceptions, delete and start
over," the other says "if you're writing ALWAYS in all caps, that's a yellow
flag; reframe with reasoning." Both are right, for different skill types.

- **Discipline skills exist because the agent will rationalize.** Soft prose
  loses to time pressure. The MUSTs are load-bearing — they are the skill.
- **Technique skills exist because the agent doesn't know the method.** Hard
  MUSTs in a technique skill make the agent rigid; explanation makes the
  agent capable. Theory-of-mind framing wins.
- **Reference skills exist because the agent needs to look something up.**
  Either register is overhead; just be scannable.

**Pick the type first, then write to the register.** Mixing registers within
a single skill is a smell — usually it means the skill is trying to do two
jobs and should be split.

**One exception: mechanical constraints carry MUSTs regardless of skill type.**
When a rule is enforced by the runtime (e.g., depth-1 skill discovery,
frontmatter `name:` matching the folder, max 1024-char frontmatter), use a
MUST even in a technique- or reference-typed skill. The register split
applies to *judgment-call* prose — discipline you must enforce against
rationalization — not to constraints the host will reject anyway.

## Directory Structure and Bundled Resources

```
skill-name/
├── SKILL.md           (required — YAML frontmatter `name:` must match folder name)
├── scripts/           (optional — executable code for deterministic tasks)
├── references/        (optional — docs loaded into context as needed)
├── assets/            (optional — files used in output: templates, fonts, icons)
├── evals/             (optional — trigger-eval and grading JSON; see references/schemas.md)
└── examples/          (optional — worked references demonstrating the skill in action)
```

**Progressive disclosure — three loading levels:**

1. **Metadata** (frontmatter: name + description) — always in context. Cost
   per skill: ~100 words. The description alone decides whether the body loads.
2. **SKILL.md body** — loaded when the skill triggers. Aim for under 500 lines.
3. **Bundled resources** — loaded on demand. Scripts can execute without their
   source loading into context at all.

**Depth-1 only.** Every immediate subdirectory of the skills root is exactly
one skill. Skills MUST NOT be nested under organizational subfolders — all
four major runtimes (Claude Code, Codex CLI, Gemini CLI, OpenCode) only
discover skills one level deep.

**When to extract to a bundled resource:**

- **Heavy reference** (100+ lines of API docs, schemas, comprehensive syntax) → `references/`
- **Reusable tool** (executable script, render helper) → `scripts/`
- **Output materials** (templates, fonts, icons used in outputs) → `assets/`
- **Everything else stays inline** — principles, concepts, code patterns < 50 lines

**Domain organization for multi-variant skills.** When one skill supports
multiple domains (cloud providers, frameworks), put the workflow in SKILL.md
and a per-variant reference in `references/aws.md`, `references/gcp.md`,
etc. The agent reads only the relevant reference file.

## SKILL.md Structure

**Frontmatter (YAML):**

- Required fields: `name` and `description`. Max 1024 characters total.
- `name`: letters, numbers, and hyphens only. Must match the folder name.
- `description`: third person, "Use when..." opening, trigger-dense, **no
  workflow summary** (see Writing the Description, next section).

**Recommended body sections:**

```markdown
# Skill Name

## Overview
What is this? Core principle in 1-2 sentences.

## When to Use
Bullet list of symptoms and use cases.
When NOT to use.

## Core Pattern  (techniques and patterns)
Before/after code comparison.

## Quick Reference  (scannable)
Table or bullets for common operations.

## Implementation
Inline code for simple patterns; link to file for heavy reference or scripts.

## Common Mistakes
What goes wrong, and how to fix it.

## Real-World Impact  (optional)
Concrete results — only if you have them and they're load-bearing.
```

## Writing the Description (The Pushy-vs-Workflow Synthesis)

The description does TWO jobs that look contradictory but aren't:

1. It must **make the agent load the skill body when relevant.** Agents
   undertrigger — they skip useful skills because the description didn't
   ring loud enough. Be aggressive about listing trigger contexts.
2. It must **NOT short-circuit the agent into acting on the description
   alone.** When a description summarizes the workflow, agents follow the
   description and skip the body — even when the body contains critical
   detail the description couldn't fit.

These reconcile cleanly: **be pushy about WHEN, never about WHAT or HOW.**

A description can be trigger-dense AND process-free at the same time. The
two failures it must avoid are independent — undertriggering is solved by
listing more contexts; body-skipping is solved by removing all process
description. You can do both.

**Examples:**

```yaml
# ❌ BAD — summarizes workflow, agent will follow this instead of reading the body
description: Use when executing plans — dispatches subagent per task with code review between tasks

# ❌ BAD — too much process detail
description: Use for TDD — write test first, watch it fail, write minimal code, refactor

# ❌ BAD — too narrow, agent won't load skill in obvious adjacent cases
description: Use when writing unit tests in Python

# ❌ BAD — abstract, no concrete triggers
description: For async testing

# ✅ GOOD — trigger-dense, pushy, process-free
description: Use when tests have race conditions, timing dependencies, or pass/fail inconsistently. Apply whenever the user mentions flakiness, hangs, timeouts, zombie processes, or "works locally but fails in CI" — even if they describe the symptom without naming async/timing as the cause.

# ✅ GOOD — pushy on triggers, no workflow
description: Use when executing implementation plans with independent tasks in the current session. Apply whenever the user references a plan file, a checklist of work, or a series of steps to carry out, even if they don't explicitly call it a "plan."
```

**Be pushy by:**

- Listing multiple phrasings of the same intent (formal, casual, abbreviated).
- Naming adjacent symptoms ("flaky," "hangs," "zombie process," "works
  locally but fails in CI") so keyword search finds the skill.
- Anticipating sloppy phrasing — typos, lowercase, "uhh," "kind of."
- Including cases where the user doesn't name the skill or its concepts.

**Be process-free by:**

- No verbs that describe the skill's internal steps ("dispatches," "reviews,"
  "runs," "iterates").
- No mentions of subagents, scripts, or tools the skill uses internally.
- No numbered phases or "first ... then ..." constructs.

**Keyword coverage.** Use the words an agent would actually search for —
error messages, symptoms, synonyms, tool names. "Hook timed out,"
"ENOTEMPTY," "race condition," "flaky," "pollution," "teardown."

**Naming.** Verb-first, active voice. `creating-skills` beats `skill-creation`.
`condition-based-waiting` beats `async-test-helpers`. Gerunds (`-ing`) work
well for processes.

## Principle of Lack of Surprise

A skill's contents must not surprise the user in their intent if described.
Don't write skills containing malware, exploit code, hidden data exfiltration,
or anything that would compromise security beyond what the skill plainly
advertises. Roleplay framings ("respond as a senior reviewer") are fine; a
skill that secretly logs to a remote endpoint is not.

## User-Communication Calibration

Skills are used by agents who serve users at very different technical
levels. Pay attention to context cues in the conversation before assuming
vocabulary:

- "Evaluation" and "benchmark" are borderline — usually OK, but watch for
  cues that the user is new to coding.
- "JSON" and "assertion" — wait for clear signals the user knows these
  terms before using them without a brief gloss.

A one-line definition costs nothing; a confused user costs the conversation.

## The Iron Law

```
NO SKILL WITHOUT A FAILING TEST FIRST
```

This applies to NEW skills AND EDITS to existing skills.

Wrote skill before testing? Delete it. Start over.
Edited skill without testing? Same violation.

**No exceptions:**

- Not for "simple additions."
- Not for "just adding a section."
- Not for "documentation updates."
- Don't keep untested changes as "reference."
- Don't "adapt" while running tests.
- Delete means delete.

**Violating the letter of the rules is violating the spirit of the rules.**

This rule applies in full to **discipline-type** skills. For technique and
reference skills, the spirit still applies — verify the skill teaches what
you think it teaches — but the test format is application or retrieval, not
pressure compliance.

## RED-GREEN-REFACTOR for Skills

| TDD Concept | Skill Creation |
|-------------|----------------|
| Test case | Pressure scenario, application scenario, or trigger-eval query |
| Production code | SKILL.md |
| Test fails (RED) | Agent violates rule, fumbles technique, or skill undertriggers |
| Test passes (GREEN) | Agent complies, applies technique correctly, or skill triggers reliably |
| Refactor | Close loopholes, tighten examples, tune description |

### RED — Watch It Fail

Run the test scenario WITHOUT the skill (or with the OLD version, if editing).
Capture verbatim:

- What choices did the agent make?
- What rationalizations did they use?
- Which queries failed to trigger the description?

### GREEN — Write Minimal Skill

Address the specific failures observed in RED. Don't add content for
hypothetical cases that never came up in baseline.

Run the scenarios WITH the skill. The agent should now comply / apply /
trigger.

### REFACTOR — Close Loopholes

The agent will find new rationalizations or near-miss query failures. Add
explicit counters. Re-test until bulletproof.

For the full pressure-subagent testing methodology, see
`references/testing-skills-with-subagents.md`.

## Testing Methodology

### Pressure Scenarios (Discipline Skills)

Combine multiple pressures to surface rationalizations:

- **Time pressure** ("the deploy is in 10 minutes")
- **Sunk cost** ("you already wrote the implementation, just write tests
  to match it")
- **Authority** ("the senior engineer said to skip TDD here")
- **Exhaustion** (long context, many turns, late in a session)

Document the exact rationalization the agent produces. Each rationalization
goes into the skill's rationalization table with an explicit counter.

### Application Scenarios (Technique Skills)

Give the agent a new problem the technique should solve. Verify they apply
the method correctly, including edge cases and variations. Look for gaps in
the instructions where the agent had to guess.

### Retrieval Scenarios (Reference Skills)

Give the agent a question whose answer is in the reference. Verify they
find it, interpret it correctly, and apply it. Common gap: covered concepts
versus covered use cases — agents need use-case-shaped entry points, not
just concept-shaped ones.

### Trigger-Eval Methodology (All Skill Types)

The description decides whether the skill ever loads. Test it directly with
a trigger-eval set of 16-20 realistic queries:

**8-10 should-trigger queries.** Different phrasings of the same intent —
formal, casual, abbreviated. Include cases where the user doesn't name the
skill or its concepts. Include uncommon use cases and competing-skill
scenarios where this skill should win.

**8-10 should-not-trigger queries.** The valuable ones are *near-misses* —
queries that share keywords or concepts but actually need a different skill
or no skill at all. Adjacent domains, ambiguous phrasing, contexts where
another tool wins. Avoid trivially-irrelevant negatives — they test
nothing.

**Realistic phrasing.** Real users include specifics — file paths, column
names, company names, URLs, a little backstory. Some are lowercase, some
have typos. A good query:

> ok so my boss just sent me this xlsx file (its in my downloads, called
> something like 'Q4 sales final FINAL v2.xlsx') and she wants me to add a
> column that shows the profit margin as a percentage. The revenue is in
> column C and costs are in column D i think

A bad query:

> Format this data.

**Manual trigger-eval workflow:**

1. Write the 16-20 queries as `evals/trigger-eval.json`:
   ```json
   [
     {"query": "the user prompt", "should_trigger": true},
     {"query": "another prompt",  "should_trigger": false}
   ]
   ```
2. For each query, dispatch a subagent in an environment with the skill
   available; ask it whether it would invoke the skill, and why. Run each
   query 3 times to get a reliable trigger rate (model output is stochastic).
3. Tabulate hit rates: true-positives (correctly triggered),
   false-negatives (should have triggered, didn't), true-negatives
   (correctly skipped), false-positives (incorrectly triggered).
4. Iterate the description against the failures. Re-run.

Automation of this loop (a scripted optimizer that proposes description
edits, splits train/test, and runs to convergence) is the future home of
`scripts/run_loop.py` — not yet shipped in this skill. The
`evals/trigger-eval.json` shape is defined inline above;
`references/schemas.md` covers the broader eval/grading JSON shapes the
future automation will use (`evals/evals.json`, `grading.json`).

**How triggering actually works.** Skills appear in the agent's available
list with their name + description. The agent decides whether to consult a
skill based on that description. Critically, simple one-step queries the
agent can handle directly often won't trigger any skill regardless of
description quality — keep eval queries substantive enough that a skill
would actually help.

## Bulletproofing Against Rationalization

Discipline skills must resist rationalization. Agents are smart and will
find loopholes under pressure. The techniques in this section apply
primarily to discipline-type skills; technique and reference skills usually
don't need them.

**Psychology background:** see `references/persuasion-principles.md` for
the research foundation (Cialdini, Meincke et al.) on authority,
commitment, scarcity, social proof, and unity — the levers that make
discipline-skill prose stick.

### Close Every Loophole Explicitly

Don't just state the rule — forbid specific workarounds:

```markdown
Write code before test? Delete it. Start over.

No exceptions:
- Don't keep it as "reference"
- Don't "adapt" it while writing tests
- Don't look at it
- Delete means delete
```

### Address Spirit-vs-Letter Arguments

Add the foundational principle early in the skill:

> **Violating the letter of the rules is violating the spirit of the rules.**

This cuts off the entire class of "I'm following the spirit" rationalizations.

### Build a Rationalization Table

Capture rationalizations from baseline (RED-phase) testing. Every excuse
the agent makes goes in the table with an explicit counter:

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "Tests after achieve the same purpose" | Tests-after = "what does this do?" Tests-first = "what should this do?" |

### Create a Red Flags List

Make it easy for the agent to self-check when rationalizing:

```markdown
## Red Flags — STOP and Start Over

- Code before test
- "I already manually tested it"
- "It's about spirit not ritual"
- "This is different because..."

All of these mean: Delete code. Start over with TDD.
```

## Flowcharts

Use flowcharts ONLY for non-obvious decision points and process loops where
the agent might stop too early. Never for reference material (use tables),
code examples (use markdown blocks), or linear instructions (use numbered
lists). Labels must have semantic meaning — no `step1`, `helper2`.

For graphviz style rules, see `references/graphviz-conventions.dot`. To
render a skill's flowcharts to SVG for visual review, use
`scripts/render-graphs.js`:

```bash
./scripts/render-graphs.js ../some-skill            # each diagram separately
./scripts/render-graphs.js ../some-skill --combine  # all diagrams in one SVG
```

## Code Examples

One excellent example beats many mediocre ones.

- Complete and runnable.
- Well-commented, explaining WHY (not WHAT).
- From a real scenario, not a contrived one.
- Ready to adapt, not a fill-in-the-blank template.

Don't implement the same example in five languages. Don't write generic
templates. Agents are good at porting; one strong example is enough.

A worked example of skill testing lives in `examples/CLAUDE_MD_TESTING.md`.

## Anti-Patterns

| Anti-pattern | Why it fails |
|--------------|--------------|
| Narrative example ("In session 2025-10-03 we found...") | Too specific, not reusable |
| Multi-language dilution (example.js, example.py, example.go) | Mediocre quality, maintenance burden |
| Code in flowcharts (`step1 [label="import fs"]`) | Can't copy-paste, hard to read |
| Generic labels (helper1, helper2, step3) | No semantic meaning |
| Description summarizes workflow | Agent follows the summary, skips the body |
| Hard MUSTs in a technique skill | Makes the agent rigid; explanation produces capability |
| @-linking other skills (`@skills/foo/SKILL.md`) | Force-loads, burns context. Use plain references instead. |

## Cross-Referencing Other Skills

When referencing other skills, use the skill name with explicit requirement
markers:

- ✅ `REQUIRED SUB-SKILL: Use test-driven-development`
- ✅ `REQUIRED BACKGROUND: You MUST understand bugfix`
- ❌ `See skills/testing/test-driven-development` — unclear if required
- ❌ `@skills/testing/test-driven-development/SKILL.md` — force-loads, burns context

## Skill Creation Checklist (TDD-Adapted)

**RED Phase — Watch It Fail:**

- [ ] Create test scenarios appropriate to the skill type (pressure for
      discipline, application for technique, retrieval for reference).
- [ ] Run scenarios WITHOUT the skill (or with the OLD version). Document
      baseline behavior verbatim.
- [ ] Identify patterns in rationalizations, fumbles, or triggering misses.
- [ ] Draft 16-20 trigger-eval queries (8-10 should-trigger + 8-10
      should-not-trigger near-misses).

**GREEN Phase — Write Minimal Skill:**

- [ ] Name uses only letters, numbers, hyphens. Matches folder name.
- [ ] YAML frontmatter, max 1024 chars, both required fields present.
- [ ] Description: trigger-dense, pushy, **no workflow summary**, third person.
- [ ] Keywords throughout body for search (errors, symptoms, tools).
- [ ] Clear overview with core principle.
- [ ] Body addresses the specific baseline failures from RED.
- [ ] Code inline OR linked to a bundled file (heavy reference → `references/`,
      executable → `scripts/`, output material → `assets/`).
- [ ] One excellent example, not multi-language.
- [ ] Run scenarios WITH the skill — verify compliance / capability / triggering.

**REFACTOR Phase — Close Loopholes:**

- [ ] Identify new rationalizations or near-miss query failures from testing.
- [ ] Add explicit counters (rationalization table, red flags list — for
      discipline skills).
- [ ] Re-test until bulletproof.
- [ ] Verify total word count is in budget (`wc -w SKILL.md`).

**Quality Checks:**

- [ ] Register matches skill type (no MUSTs in technique skills, no soft
      reframing in discipline skills).
- [ ] Small flowchart only where the decision is non-obvious.
- [ ] Quick reference table where it helps.
- [ ] Common mistakes section.
- [ ] No narrative storytelling.
- [ ] Supporting files only for tools or heavy reference.

## STOP Before Moving to the Next Skill

After writing ANY skill, you MUST STOP and complete the checklist above
before moving on. Do not batch multiple skills without testing each.
Deploying untested skills is deploying untested code.

## The Bottom Line

Creating skills IS TDD for process documentation.

Same Iron Law: no skill without a failing test first.
Same cycle: RED (watch fail) → GREEN (write minimal) → REFACTOR (close loopholes).
Same benefits: better quality, fewer surprises, bulletproof results.

For Anthropic's official skill-authoring guidance (the longer-form companion
to this skill), see `references/anthropic-best-practices.md`.
