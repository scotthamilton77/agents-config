---
name: self-improving-agent
model: sonnet
allowed-tools: Read, Write, Edit, Glob, Grep
description: Use when receiving any correction, repeated mistake, or behavioral feedback from the user - ensures lessons persist beyond the current conversation as actionable prevention rules
---

# Self-Improving Agent

## Core Principle

**Corrections that die with the conversation will be repeated.** When corrected, write a persistent prevention rule that survives context compaction and session boundaries.

## When to Use

- User says "I told you before..." / "Stop doing X" / "You keep..."
- Any explicit correction of your behavior or output
- Post-incident review of what went wrong
- User provides a preference you didn't know about

## When NOT to Use

- One-off factual correction ("that endpoint is /v2 not /v1")
- Already covered by existing rules
- Obvious from the codebase itself

## The Process

### 1. Acknowledge briefly

Don't grovel. One sentence, then act.

### 2. Classify and locate

| Correction Type | Write To |
|---|---|
| Project convention (naming, patterns, structure) | Project `CLAUDE.md` or `AGENTS.md` |
| Cross-project preference (style, behavior, workflow) | User `~/.claude/AGENTS.md` |
| Tool/environment quirk | Nearest relevant config file |

Before adding a rule, check if a related rule already exists. If so, strengthen it instead of creating a duplicate.

### 3. Write a prevention rule

**Good rules are:**
- **Specific**: "Use `unknown` + type guards, never `any`" not "use proper types"
- **Falsifiable**: You can objectively check if you violated it
- **Actionable**: Clear what to do instead
- **Compact**: One line, fits existing section structure

**Example transformation:**
- Bad: "Be more careful with imports"
- Good: "Always use absolute imports from `@/` — never relative paths crossing module boundaries"

### 4. Capture rationale in memory

After writing the prevention rule, evaluate whether the *reasoning* behind the correction is non-obvious — the incident, the tradeoff, the "we got burned when..." context. If it is, write a `feedback` memory using your built-in memory system to preserve the *why* alongside the rule's *what*.

Skip this when the rule is self-explanatory (e.g., "use absolute imports"). Do it when the rule only makes sense with backstory (e.g., "never mock the database" needs the migration incident that motivated it).

### 5. Consolidate

- 3+ rules about same concept → merge into 1 strong rule
- Rule duplicates existing constraint → strengthen existing instead
- Rule states what Claude does by default → delete it

### 6. Continue with the task

Write the rule, then proceed. Don't let self-improvement derail the work.

## Anti-Patterns

| Pattern | Problem |
|---|---|
| "I'll do better" without writing a rule | Promise evaporates with context |
| Writing vague rules | Claude ignores them anyway |
| Adding without checking existing rules | Rule bloat degrades agent performance |
| Recording every minor correction | Signal-to-noise ratio drops |

## Red Flags — You're Skipping This

- You acknowledged a correction but didn't open any config file
- You said "noted" or "understood" without writing anything
- You rationalized "this is too minor to record"
- You applied the fix in-context but wrote nothing persistent
- You wrote a rule but didn't check for existing related rules first

**All of these mean: STOP. Open the config file. Write the rule. Then continue.**

## Verification Checklist

- [ ] Rule is written to a persistent file (not just acknowledged in conversation)
- [ ] Checked for existing related rules — no duplicates introduced
- [ ] Rule is specific and falsifiable (not "be more careful")
- [ ] Rule is in the correct scope (project vs. user-level)
- [ ] If rationale is non-obvious, a `feedback` memory captures the why
- [ ] Continued with the original task after writing the rule
