---
name: optimize-my-skill
model: sonnet
allowed-tools: Read, Write, Edit, Glob, Grep, AskUserQuestion
description: Audits and improves existing SKILL.md files for discoverability, progressive disclosure, and methodology rigor. Use when asked to optimize a skill, when reviewing a skill folder for quality, or when a SKILL.md needs frontmatter or body cleanup. Do NOT use for agent persona files or AGENTS.md configuration files.
---

# Optimize My Skill

Audit and improve existing SKILL.md files for clarity, discoverability, and effectiveness. This skill is for *auditing and improving* existing skills — if a `writing-skills` skill is available (e.g. `superpowers:writing-skills`), prefer it for *creating* new skills from scratch.

## Phase 1: Discover and Read

Find all SKILL.md files in the target scope. For each one, read the complete file (frontmatter + body) and also check the skill's folder structure.

Scope resolution from the invoking command's argument:

- **Specific skill name** (e.g. `bugfix`, `writing-unit-tests`) — search for a folder whose `name` frontmatter field or directory name matches. Optimize that single skill.
- **Directory path** (e.g. `~/.claude/skills/` or `.claude/skills/`) — enumerate every immediate subdirectory containing a `SKILL.md`. Optimize all of them.
- **Empty argument** — the command layer is responsible for probing default locations and either passing a resolved path or aborting with a "no skills found" message. This skill expects a resolved scope.

For each discovered skill, also inventory:

- Presence of `scripts/` (executable code for deterministic operations)
- Presence of `references/` (detailed docs, API guides, lengthy examples)
- Presence of `assets/` (templates, fonts, icons used in output)
- Any stray `.md` files at the top level (only `SKILL.md` belongs there)

## Phase 2: Assess Against Quality Criteria

Rate each skill against the following areas. Produce a written assessment for every skill in scope before proposing changes.

### Frontmatter

Per SKILLS_PRIMER (see `references/SKILLS_PRIMER.md`):

**Required fields:**

| Criterion | Good | Bad |
|-----------|------|-----|
| **name** | lowercase-kebab-case, matches folder name | camelCase, spaces, uppercase, mismatched |
| **description** | Explains WHEN to invoke with concrete triggers | Explains what the skill does generically |
| **description** | Single line, under 1024 characters | Multi-line YAML (`>` or `\|`), or over limit |
| **description** | Mentions observable situations | Lists abstract keywords |
| **description** | Includes negative triggers ("Do NOT use for...") where appropriate | No scope boundaries, risks over-triggering |

**Security checks** (fail the skill if violated):

- [ ] No XML angle brackets (`<` or `>`) in frontmatter values
- [ ] Name does not contain "claude" or "anthropic" (reserved)

**Optional fields** (flag if present but malformed, suggest if beneficial):

| Field | Purpose | Validation |
|-------|---------|------------|
| **license** | Open-source license identifier | Valid SPDX (MIT, Apache-2.0, etc.) |
| **allowed-tools** | Restrict tool access | Space-separated (e.g. `"Bash(python:*) WebFetch"`) or comma-separated (e.g. `Read, Write, Edit`) — both accepted by Claude Code |
| **compatibility** | Environment requirements | 1-500 characters |
| **metadata** | Custom key-value pairs | Valid YAML object; suggest: author, version, mcp-server |

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

Per SKILLS_PRIMER (see `references/SKILLS_PRIMER.md`): skills use a three-level progressive disclosure system to minimize token usage:

| Level | What | Loaded When |
|-------|------|-------------|
| **1. Frontmatter** | name + description | Always (system prompt) |
| **2. SKILL.md body** | Full instructions | When skill is triggered |
| **3. Linked files** | references/, scripts/, assets/ | On demand within the skill |

Assess:

- [ ] **SKILL.md is the only `.md` file**: No README.md inside the skill folder (all docs go in SKILL.md or references/)
- [ ] **SKILL.md size**: Under 500 lines. If over, flag sections that should move to `references/`
- [ ] **Heavy content in references/**: Detailed docs, API guides, lengthy examples belong in `references/`, linked from SKILL.md
- [ ] **Scripts in scripts/**: Executable code (Python, Bash) for deterministic operations lives in `scripts/`
- [ ] **Templates in assets/**: Templates, fonts, icons used in output belong in `assets/`

### Body Content

Per SKILLS_PRIMER (see `references/SKILLS_PRIMER.md`):

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
- [ ] SKILL.md over 500 lines without using references/ for overflow
- [ ] README.md inside the skill folder
- [ ] XML angle brackets in frontmatter

## Phase 3: Propose Improvements

For each skill that needs work, present a structured proposal. Do not silently rewrite — surface the change and the rationale so the user can accept, modify, or reject.

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

For each modified skill, suggest tests the user can run to confirm the changes work:

**Triggering tests** — ask Claude "When would you use the [skill name] skill?" and verify it quotes the right triggers:

- Should trigger: [2-3 natural phrases that should activate this skill]
- Should NOT trigger: [2-3 unrelated queries it should ignore]

**Functional check** — after applying changes, verify the skill still produces correct behavior on a representative task. If the skill includes deterministic scripts, run them against a known input/output pair.

## Phase 5: Confirm and Apply

Present all proposed changes as a single summary table before writing anything:

```
| Skill | Change Type | Description |
|-------|-------------|-------------|
| bugfix | description rewrite | Added negative triggers, clarified scope |
| writing-unit-tests | body: add red flags | Missing rationalization table |
| my-workflow | structure: extract refs | Moved API docs to references/ |
| ... | no changes needed | Already well-structured |
```

**Wait for user confirmation before writing any files.** Use `AskUserQuestion` to capture the accept/reject decision per skill if the batch is large.

Apply approved changes. Show a diff for each modified file so the user can verify the edit landed correctly.

## Reference: What Makes Skills Effective

See `references/SKILLS_PRIMER.md` for the full file structure, frontmatter schema, body structure template, and key principles.
