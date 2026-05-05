---
name: ralf-review
model: opus[1m]
effort: high
argument-hint: "[bead-id, file path, or review target text]"
description: Explicit invocation only — bounded adversarial review cycles for specs/design/code; inner-methodology only (no worktree or delivery ownership)
---

# ralf-review

Adversarial multi-pass review methodology for a target artifact. This skill is read-only with respect to repository code.

Caller owns outer workflow:
- worktree setup
- branch / PR / delivery
- formula stage orchestration

## Invocation guard

Invoke only when one of these is true:
- user explicitly asks for `ralf-review`
- a formula review-step dispatch contract selects `ralf-review`

Do not invoke as a peer workflow alongside bead orchestration.

## Core invariants

1. **Iteration** — multi-pass, bounded by a cycle cap.
2. **Independence** — each cycle uses a new fresh-eyes subagent with no prior-cycle context.
3. **Adversarial posture** — each pass seeks omissions, ambiguity, inconsistency, and risk.
4. **Convergence** — stop when findings are non-significant or cycle budget is exhausted.

## Context and argument contract

Argument accepts:
- bead ID (review bead spec/acceptance)
- file path (review the referenced document)
- free-text target description

Bead-driven mode detection:
- argument parses as a bead ID, and
- `bd show <id>` succeeds

No worktree checks are performed in this skill.

## Cycle budget contract

Default cycle cap: `RALF_REVIEW_DEFAULT_CYCLES=2`

When bead-driven, read labels:
```bash
bd label list <id> --json
```

Interpretation:
- `ralf:cycles=N` where `N` is integer `1..20` overrides default
- multiple `ralf:cycles=*` labels => warn and use default
- malformed or out-of-range `ralf:cycles=*` => warn and use default

## Review loop

Per cycle:
1. Dispatch a fresh-eyes reviewer with the original target context.
2. Collect findings with severity and concrete recommendations.
3. Evaluate significance:
   - non-significant findings => converge
   - significant findings => continue until cap

This skill reports findings and rationale. It does not implement code changes.

## Convergence exhaustion behavior

If max cycles are reached and significant risks remain:
- bead-driven: apply human-flag protocol on bead with unresolved-risk summary
- standalone: ask user whether to continue with additional cycles

## Output contract

Report:
- cycles run and convergence result
- prioritized findings
- unresolved concerns (if any)
- recommended next action
