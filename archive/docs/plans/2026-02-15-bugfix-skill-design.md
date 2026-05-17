# Bugfix Skill Design

## Purpose

Standalone debugging skill that gathers evidence from three parallel angles before diagnosing. Triggers on bugs with unclear origins where the root cause isn't obvious.

## Name

`bugfix`

## Trigger

Bugs with unclear origins — multiple files could be involved, symptom doesn't point to a single line. Systematic-debugging remains default for simpler/obvious bugs.

## Relationship to Existing Skills

- **Standalone alternative** to `systematic-debugging` (plugin-managed, can't modify)
- Cross-references `root-cause-tracing` for deep call-stack investigation
- Cross-references `writing-unit-tests` for test quality guidance
- Complements `dispatching-parallel-agents` (uses parallel subagents as core mechanism)

## Workflow

```
Bug reported [describe symptom]
  │
  ├─ Spawn 3 parallel tasks ─────────────────────────────────┐
  │   [1] Git archaeology: last 20 commits on affected files  │
  │   [2] Reproduce: minimal failing test, confirm failure    │
  │   [3] Data flow trace: read source, trace entry → failure │
  │                                                           │
  ├─ All 3 complete ──────────────────────────────────────────┘
  │
  ├─ Synthesize into root cause analysis
  │   - If any thread inconclusive → say so, don't speculate
  │   - If root cause identified → propose fix
  │
  ├─ Implement fix
  ├─ Run failing test → confirm green
  ├─ Run full test suite
  └─ Commit only if ALL tests pass
```

## Key Differentiators

| Aspect | systematic-debugging | bugfix (this skill) |
|--------|---------------------|---------------------|
| Investigation | Sequential 4-phase | 3 parallel threads |
| Git history | "Check recent changes" (vague) | Structured: last 20 commits on affected files |
| Test reproduction | Phase 4 (after diagnosis) | Part of investigation (before diagnosis) |
| Synthesis | Implicit | Explicit gate before any fix |
| Inconclusive results | Not addressed | Must declare, not speculate |

## What It Does NOT Cover

- Deep call-stack tracing → defer to `root-cause-tracing`
- Test quality patterns → defer to `writing-unit-tests`
- Architecture-level problems → defer to `systematic-debugging` Phase 4.5
- Timing/race conditions → defer to `condition-based-waiting`

## Skill Structure

Self-contained `SKILL.md` in `~/.claude/skills/bugfix/`. No supporting files needed.

Sections: Overview, When to Use (with flowchart), The Three Threads, Synthesis Gate, Implementation Phase, Red Flags, Rationalization Table, Quick Reference.
