# Skill Anatomy and Conventions

Layout, frontmatter, body shape, cross-referencing, and the two content
constraints. Consult while writing a skill; the SKILL.md body carries only
what you need to *decide* how to proceed.

## Directory Structure

```
skill-name/
├── SKILL.md           (required — frontmatter `name:` must match folder name)
├── scripts/           (optional — executable code for deterministic tasks)
├── references/        (optional — docs loaded into context as needed)
├── assets/            (optional — templates, fonts, icons used in output)
├── evals/             (optional — trigger-eval and grading JSON; see schemas.md)
└── examples/          (optional — worked references)
```

**When to extract:** heavy reference (100+ lines of docs, schemas, syntax) →
`references/`; reusable tool → `scripts/`; output material → `assets/`.
Everything else stays inline — principles, concepts, code patterns under 50
lines.

**Domain organization for multi-variant skills.** When one skill supports
multiple domains (cloud providers, frameworks), put the workflow in SKILL.md
and a per-variant reference in `references/aws.md`, `references/gcp.md`, etc.
The agent reads only the relevant reference file.

## Frontmatter

YAML, max 1024 characters total.

- `name` (required) — letters, numbers, and hyphens only. Must match the
  folder name.
- `description` (required) — third person, "Use when..." opening,
  trigger-dense, **no workflow summary**. See `descriptions.md`.
- `model:` (optional) — do not pin a small or cheap model. A skill runs
  inside the parent conversation and inherits its full context, so a model
  window smaller than that context errors (`ContextLimitExceeded`). Pin small
  models on agents, which get fresh context, not on skills.

## Recommended Body Sections

```markdown
# Skill Name

## Overview
What is this? Core principle in 1-2 sentences.

## When to Use
Bullet list of symptoms and use cases. When NOT to use.

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

## Cross-Referencing Other Skills

Use the skill name with an explicit requirement marker:

- ✅ `REQUIRED SUB-SKILL: Use tdd`
- ✅ `REQUIRED BACKGROUND: You MUST understand diagnosing-bugs`
- ❌ `See skills/testing/tdd` — unclear if required
- ❌ `@skills/testing/tdd/SKILL.md` — force-loads, burns
  context

## Principle of Lack of Surprise

A skill's contents must not surprise the user in their intent if described.
Don't write skills containing malware, exploit code, hidden data
exfiltration, or anything that would compromise security beyond what the
skill plainly advertises. Roleplay framings ("respond as a senior reviewer")
are fine; a skill that secretly logs to a remote endpoint is not.

## User-Communication Calibration

Skills are used by agents who serve users at very different technical levels.
Pay attention to context cues in the conversation before assuming vocabulary:

- "Evaluation" and "benchmark" are borderline — usually OK, but watch for
  cues that the user is new to coding.
- "JSON" and "assertion" — wait for clear signals the user knows these terms
  before using them without a brief gloss.

A one-line definition costs nothing; a confused user costs the conversation.
