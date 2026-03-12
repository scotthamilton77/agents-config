# Optimize Skill

You are an expert at writing effective Claude Code skill files. Your task is to audit and improve SKILL.md files for clarity, discoverability, and effectiveness.

> **Tip**: If a `writing-skills` skill is available (e.g. `superpowers:writing-skills`), prefer invoking it when *creating* new skills from scratch. This command is for *auditing and improving* existing skills.

`$ARGUMENTS` specifies the target:
- **Skill name**: "bugfix", "writing-unit-tests" — optimizes that single skill
- **Directory path**: "~/.claude/skills/" or ".claude/skills/" — optimizes all skills in that directory
- **Empty**: defaults to all skills in `.claude/skills/`

## Phase 1: Discover and Read

Find all SKILL.md files in the target scope. For each, read the complete file (frontmatter + body). Also check the skill's folder structure (scripts/, references/, assets/).

If `$ARGUMENTS` names a specific skill, search for it by matching the `name` field in frontmatter or the directory name.

## Phase 2: Assess Against Quality Criteria

Rate each skill against these areas:

### Frontmatter

**Required fields:**

| Criterion | Good | Bad |
|-----------|------|-----|
| **name** | lowercase-kebab-case, matches folder name | camelCase, spaces, uppercase, mismatched |
| **description** | Explains WHEN to invoke with concrete triggers | Explains what the skill does generically |
| **description** | Single line, under 1024 characters | Multi-line YAML (`>` or `\|`), or over limit |
| **description** | Mentions observable situations | Lists abstract keywords |
| **description** | Includes negative triggers ("Do NOT use for...") where appropriate | No scope boundaries, risks over-triggering |

**Optional fields** (flag if present but malformed, suggest if beneficial):

| Field | Purpose | Validation |
|-------|---------|------------|
| **license** | Open-source license identifier | Valid SPDX (MIT, Apache-2.0, etc.) |
| **allowed-tools** | Restrict tool access | Space-separated tool patterns, e.g. `"Bash(python:*) WebFetch"` |
| **compatibility** | Environment requirements | 1-500 characters |
| **metadata** | Custom key-value pairs | Valid YAML object; suggest: author, version, mcp-server |

**Security checks** (fail the skill if violated):

- [ ] No XML angle brackets (`<` or `>`) in frontmatter values
- [ ] Name does not contain "claude" or "anthropic" (reserved)

**Description formula that works:** `[What it does]. Use when [situation A], [situation B], or [situation C]. Do NOT use for [exclusion].`

Examples of effective descriptions:
- "Use when encountering a bug with unclear origins, when multiple files could be involved, or when the symptom does not obviously point to a single root cause"
- "Use when writing unit tests, reviewing test code, or when asked to add tests to complex/untestable code"
- "Manages Linear project workflows including sprint planning and task creation. Use when user mentions 'sprint', 'Linear tasks', or 'project planning'. Do NOT use for general task lists unrelated to Linear."

Examples of ineffective descriptions:
- "Testing helper: test, vitest, jest, coverage, fix suite" (keyword stuffing — Claude isn't a search engine)
- "Helps write better code" (vague, no trigger context)
- "A skill for debugging" (describes what, not when)

### Folder Structure (Progressive Disclosure)

Skills use a three-level progressive disclosure system to minimize token usage:

| Level | What | Loaded When |
|-------|------|-------------|
| **1. Frontmatter** | name + description | Always (system prompt) |
| **2. SKILL.md body** | Full instructions | When skill is triggered |
| **3. Linked files** | references/, scripts/, assets/ | On demand within the skill |

Assess:

- [ ] **SKILL.md is the only `.md` file**: No README.md inside the skill folder (all docs go in SKILL.md or references/)
- [ ] **SKILL.md size**: Under 5,000 words. If over, flag sections that should move to `references/`
- [ ] **Heavy content in references/**: Detailed docs, API guides, lengthy examples belong in `references/`, linked from SKILL.md
- [ ] **Scripts in scripts/**: Executable code (Python, Bash) for deterministic operations lives in `scripts/`
- [ ] **Templates in assets/**: Templates, fonts, icons used in output belong in `assets/`

### Body Content

| Criterion | Present? | Quality (1-5) | Notes |
|-----------|----------|---------------|-------|
| **Core principle** | | | One-sentence iron law the skill enforces |
| **When to use / When not to use** | | | Clear decision criteria, ideally a decision tree |
| **The process** | | | Step-by-step methodology, not vague advice |
| **Concrete examples** | | | Good vs bad patterns with real code |
| **Red flags / rationalizations** | | | Table of excuses and rebuttals |
| **Verification checklist** | | | How to confirm the skill was applied correctly |
| **Error handling** | | | What to do when things go wrong |

### Anti-Patterns to Flag

- [ ] Generic advice Claude would follow without being told ("write clean code")
- [ ] Descriptions instead of examples for code patterns
- [ ] No explicit "when NOT to use" criteria (over-triggering risk)
- [ ] No negative triggers in description (over-triggering risk)
- [ ] Process steps that are vague imperatives ("be careful", "consider")
- [ ] Missing decision trees for ambiguous situations
- [ ] No red flags section (skill gets rationalized away)
- [ ] Body content duplicates what's in the frontmatter description
- [ ] SKILL.md over 5,000 words without using references/ for overflow
- [ ] README.md inside the skill folder
- [ ] XML angle brackets in frontmatter

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

**Structural improvements** (if any):
- [specific addition/removal/transformation with rationale]
- [files to move to references/, scripts to extract, etc.]

**Body improvements** (if any):
- [specific addition/removal/transformation with rationale]

### What NOT to Change

- Do not rewrite skill body content that is already effective
- Do not add keyword lists or "trigger" words — Claude matches semantically, not by keyword
- Do not remove opinionated methodology in favor of generic advice
- Do not add optional frontmatter fields unless they provide clear value for the specific skill

## Phase 4: Suggest Testing

For each modified skill, suggest tests the user can run:

**Triggering tests** — ask Claude "When would you use the [skill name] skill?" and verify it quotes the right triggers:
- Should trigger: [2-3 natural phrases that should activate this skill]
- Should NOT trigger: [2-3 unrelated queries it should ignore]

**Functional check** — after applying changes, verify the skill still produces correct behavior on a representative task.

## Phase 5: Confirm and Apply

Present all proposed changes as a summary table:

```
| Skill | Change Type | Description |
|-------|-------------|-------------|
| bugfix | description rewrite | Added negative triggers, clarified scope |
| writing-unit-tests | body: add red flags | Missing rationalization table |
| my-workflow | structure: extract refs | Moved API docs to references/ (was 7k words) |
| ... | no changes needed | Already well-structured |
```

**Wait for user confirmation before writing any files.**

Apply approved changes. Show a diff for each modified file.

## Reference: What Makes Skills Effective

### File Structure

```
your-skill-name/
├── SKILL.md              # Required — main skill file (must be exactly SKILL.md)
├── scripts/              # Optional — executable code (Python, Bash, etc.)
├── references/           # Optional — detailed docs, API guides, examples
└── assets/               # Optional — templates, fonts, icons
```

### Frontmatter That Works

```yaml
---
name: skill-name
description: What it does. Use when [situation A], [situation B], or [situation C]. Do NOT use for [exclusion].
---
```

Optional fields when useful:

```yaml
---
name: skill-name
description: What it does. Use when [situation A], [situation B], or [situation C].
license: MIT
allowed-tools: "Bash(python:*) WebFetch"
compatibility: Requires Python 3.10+
metadata:
  author: Your Name
  version: 1.0.0
---
```

### Body Structure That Works

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
2. **Progressive disclosure saves tokens**: Frontmatter is always loaded, body only when triggered, linked files only when needed. Keep SKILL.md under 5,000 words.
3. **Opinionated > generic**: "Never mock more than 2 dependencies" beats "use mocks judiciously."
4. **Decision trees > paragraphs**: Ambiguity is where skills fail. Trees eliminate it.
5. **Negative triggers prevent over-firing**: "Do NOT use for X" in descriptions is as important as "Use when Y."
6. **Red flags prevent rationalization**: Without them, Claude skips the skill "just this once."
7. **Code > language for validation**: For critical checks, bundle a script in `scripts/` rather than relying on language instructions. Code is deterministic; interpretation isn't.
8. **Body content is the skill**: The frontmatter gets you discovered, the body gets you followed.

---

Now find the skills at $ARGUMENTS and begin your assessment.
