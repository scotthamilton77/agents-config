# Optimize Skill

You are an expert at writing effective Claude Code skill files. Your task is to audit and improve SKILL.md files for clarity, discoverability, and effectiveness.

`$ARGUMENTS` specifies the target:
- **Skill name**: "bugfix", "writing-unit-tests" — optimizes that single skill
- **Directory path**: "~/.claude/skills/" or ".claude/skills/" — optimizes all skills in that directory
- **Empty**: defaults to all skills in `.claude/skills/`

## Phase 1: Discover and Read

Find all SKILL.md files in the target scope. For each, read the complete file (frontmatter + body).

If `$ARGUMENTS` names a specific skill, search for it by matching the `name` field in frontmatter or the directory name.

## Phase 2: Assess Against Quality Criteria

Rate each skill against these areas:

### Frontmatter (the only valid fields are `name` and `description`)

| Criterion | Good | Bad |
|-----------|------|-----|
| **name** | lowercase-kebab-case | camelCase, spaces, uppercase |
| **description** | Explains WHEN to invoke with concrete triggers | Explains what the skill does generically |
| **description** | Single line, no multiline YAML (`>` or `\|`) | Multi-line string |
| **description** | Mentions observable situations | Lists abstract keywords |

**Description formula that works:** "Use when [observable situation], [another situation], or [another situation]"

Examples of effective descriptions:
- "Use when encountering a bug with unclear origins, when multiple files could be involved, or when the symptom does not obviously point to a single root cause"
- "Use when writing unit tests, reviewing test code, or when asked to add tests to complex/untestable code"
- "Use when receiving any correction, repeated mistake, or behavioral feedback from the user"

Examples of ineffective descriptions:
- "Testing helper: test, vitest, jest, coverage, fix suite" (keyword stuffing — Claude isn't a search engine)
- "Helps write better code" (vague, no trigger context)
- "A skill for debugging" (describes what, not when)

### Body Content

| Criterion | Present? | Quality (1-5) | Notes |
|-----------|----------|---------------|-------|
| **Core principle** | | | One-sentence iron law the skill enforces |
| **When to use / When not to use** | | | Clear decision criteria, ideally a decision tree |
| **The process** | | | Step-by-step methodology, not vague advice |
| **Concrete examples** | | | Good vs bad patterns with real code |
| **Red flags / rationalizations** | | | Table of excuses and rebuttals |
| **Verification checklist** | | | How to confirm the skill was applied correctly |

### Anti-Patterns to Flag

- [ ] Generic advice Claude would follow without being told ("write clean code")
- [ ] Descriptions instead of examples for code patterns
- [ ] No explicit "when NOT to use" criteria (overuse risk)
- [ ] Process steps that are vague imperatives ("be careful", "consider")
- [ ] Missing decision trees for ambiguous situations
- [ ] No red flags section (skill gets rationalized away)
- [ ] Body content duplicates what's in the frontmatter description

## Phase 3: Propose Improvements

For each skill that needs work, present:

**Skill**: `[name]` (`[path]`)
**Current description**:
```
[existing description]
```
**Proposed description**:
```
[improved description]
```
**Why**: [one sentence on what changed and why]

**Body improvements** (if any):
- [specific addition/removal/transformation with rationale]

### What NOT to Change

- Do not rewrite skill body content that is already effective
- Do not add keyword lists or "trigger" words — Claude matches semantically, not by keyword
- Do not remove opinionated methodology in favor of generic advice

## Phase 4: Confirm and Apply

Present all proposed changes as a summary table:

```
| Skill | Change Type | Description |
|-------|-------------|-------------|
| bugfix | description rewrite | Clarified trigger situations |
| writing-unit-tests | body: add red flags | Missing rationalization table |
| ... | no changes needed | Already well-structured |
```

**Wait for user confirmation before writing any files.**

Apply approved changes. Show a diff for each modified file.

## Reference: What Makes Skills Effective

### Structure That Works

```yaml
---
name: skill-name
description: Use when [situation A], [situation B], or [situation C]
---
```

Followed by:

```markdown
# Skill Name

## Core Principle
One iron law. The thing this skill enforces above all.

## When to Use
Decision tree or clear criteria. Include "when NOT to use."

## The Process
Numbered steps with concrete actions. Not "consider" — "do."

## Examples
Good vs bad with real code. Show don't tell.

## Red Flags / Common Rationalizations
Table of excuses and why they're wrong.

## Verification Checklist
How to confirm the skill was applied correctly.
```

### Key Principles

1. **Descriptions are discovery hooks**: They tell Claude WHEN to invoke, not WHAT the skill does. Claude reads the body for the "what."
2. **Opinionated > generic**: "Never mock more than 2 dependencies" beats "use mocks judiciously."
3. **Decision trees > paragraphs**: Ambiguity is where skills fail. Trees eliminate it.
4. **Red flags prevent rationalization**: Without them, Claude skips the skill "just this once."
5. **Body content is the skill**: The frontmatter gets you discovered, the body gets you followed.

---

Now find the skills at $ARGUMENTS and begin your assessment.
