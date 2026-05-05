---
name: ralf-implement
model: opus[1m]
effort: xhigh
argument-hint: "[bead-id or task description]"
description: Explicit invocation only — iterative implementation with adversarial fresh-eyes cycles; inner-methodology only (no worktree or delivery ownership)
---

# ralf-implement

Iterative implementation methodology for code changes. This skill owns only the inner quality loop.

Caller owns outer workflow:
- worktree setup
- branch / PR / delivery
- formula stage orchestration

## Invocation guard

Invoke only when one of these is true:
- user explicitly asks for `ralf-implement`
- a formula step dispatch contract selects `ralf-implement` (for example: `ralf:required` present on an implement step)

Do not invoke as a peer workflow alongside bead orchestration.

## Core invariants

1. **Iteration** — multi-pass, bounded by a cycle cap.
2. **Independence** — each fresh-eyes pass is a new subagent with no prior-cycle context.
3. **Adversarial posture** — each pass searches for missing, weak, or incorrect behavior.
4. **Convergence** — stop when findings are non-significant or cycle budget is exhausted.

## Context and argument contract

Argument accepts:
- bead ID
- free-text task description

Bead-driven mode detection:
- argument parses as a bead ID, and
- `bd show <id>` succeeds

No worktree checks are performed in this skill. Run against the caller-selected working copy.

## Cycle budget contract

Default cycle cap: `RALF_IMPLEMENT_DEFAULT_CYCLES=3`

When bead-driven, read labels:
```bash
bd label list <id> --json
```

Interpretation:
- `ralf:cycles=N` where `N` is integer `1..20` overrides default
- multiple `ralf:cycles=*` labels => warn and use default
- malformed or out-of-range `ralf:cycles=*` => warn and use default

Note: this skill reads labels; caller controls whether dispatch occurs.

## Iteration routing

Per cycle:
1. Implement/fix in current working copy.
2. Run project quality checks relevant to changed scope.
3. Run fresh-eyes pass:
   - cycle 1: foreign-eyes via Codex
   - cycle 2: foreign-eyes via Gemini
   - cycle 3+: pure-Claude fresh-eyes
4. Apply valid findings and continue until converged.

Foreign-agent failures degrade cleanly to pure fresh-eyes; cycle still counts.

## Convergence exhaustion behavior

If max cycles are reached and significant work remains:
- bead-driven: apply human-flag protocol on bead with summary of unresolved risks
- standalone: ask user whether to continue with additional cycles

## Output contract

Report:
- cycles run and convergence result
- significant fixes applied
- unresolved concerns (if any)
- any foreign-eyes degradation observed

