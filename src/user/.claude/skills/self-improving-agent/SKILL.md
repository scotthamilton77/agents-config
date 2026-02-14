---
name: self-improving-agent
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

**Bad rules:** "Be more careful with X", "Remember to Y", "Try to Z"

### 4. Consolidate

- 3+ rules about same concept → merge into 1 strong rule
- Rule duplicates existing constraint → strengthen existing instead
- Rule states what Claude does by default → delete it

### 5. Continue with the task

Write the rule, then proceed. Don't let self-improvement derail the work.

## Decision Threshold

Write a persistent rule when:
- The mistake could recur in a future session
- The correction reflects a preference Claude can't infer from code
- You've been corrected about the same thing before

Skip when:
- One-off factual correction ("that endpoint is /v2 not /v1")
- Already covered by existing rules
- Obvious from the codebase

## Anti-Patterns

| Pattern | Problem |
|---|---|
| "I'll do better" without writing a rule | Promise evaporates with context |
| Writing vague rules | Claude ignores them anyway |
| Adding without checking existing rules | Rule bloat degrades agent performance |
| Recording every minor correction | Signal-to-noise ratio drops |

## Red Flags - You're Skipping This

- You acknowledged a correction but didn't open any config file
- You said "noted" or "understood" without writing anything
- You rationalized "this is too minor to record"
- You applied the fix in-context but wrote nothing persistent
- You wrote a rule but didn't check for existing related rules first

**All of these mean: STOP. Open the config file. Write the rule. Then continue.**
