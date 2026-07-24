---
name: ralf-review
model: opus[1m]
effort: xhigh
argument-hint: "[review target + criteria + optional max cycles]"
description: Explicit invocation only — bounded adversarial review cycles for specs/design/code; inner-methodology only (no worktree or delivery ownership)
---

# ralf-review

Adversarial multi-pass review methodology for a target artifact.

The caller must provide the target artifact, review criteria, relevant context, and optional max cycle count. This skill owns no outer workflow state: no worktree setup, branch delivery, PR creation, tracker updates, or dispatch decisions.

## Required inputs

The invocation must include or already have in context:
- target artifact or target text
- review criteria or Definition of Done
- relevant background/context needed to judge the target
- optional max cycles, integer `1..20`

Fail fast when the target is missing, the review criteria are missing, the optional max cycle count is malformed or out of range, or a referenced target file cannot be read.

## Core invariants

1. **Iteration** — multi-pass, bounded by a cycle cap.
2. **Independence** — each cycle uses a new fresh-eyes subagent with no prior-cycle context.
3. **Adversarial posture** — each pass seeks omissions, ambiguity, inconsistency, and risk.
4. **Convergence** — stop when findings are non-significant or cycle budget is exhausted.

## Cycle budget contract

Default cycle cap: `RALF_REVIEW_DEFAULT_CYCLES=2`

The caller may pass an explicit max cycle count. If absent, use the default. Reject malformed, duplicate, or out-of-range cycle inputs instead of guessing.

## Review loop

Per cycle:
1. Dispatch a fresh-eyes reviewer with the original target context.
2. Collect findings with severity and concrete recommendations.
3. Evaluate significance:
   - non-significant findings => converge
   - significant findings => continue until cap

This skill reports findings, rationale, and convergence state. It does not implement code changes. The caller decides whether to continue, defer, escalate, or accept with reservations.

## Severity rubric

- **Blocking** — prevents the target from being evaluated, implemented, shipped, or safely used.
- **Critical** — violates explicit requirements, creates security/data-loss risk, or makes the target materially incorrect.
- **Major** — leaves important ambiguity, missing scope, weak acceptance criteria, maintainability risk, or integration risk.
- **Minor** — localized clarity issue, documentation gap, naming issue, or small missing guard that does not threaten correctness.

## Output contract

Produce a structured report with:
- **Score:** `PASS`, `PASS_WITH_RESERVATIONS`, or `FAIL`
- **Score rationale:** one or two concrete sentences
- **Cycles run:** `<n>/<max>`
- **Severity counts:** blocking, critical, major, minor
- **Prioritized findings:** grouped by severity
- **Remaining concerns:** unresolved issues after the final cycle
- **Recommended caller action:** accept, revise, continue, or defer

Scoring:
- `PASS` — final cycle found no blocking, critical, or major quality concerns.
- `PASS_WITH_RESERVATIONS` — cycle budget was exhausted; final cycle found no blocking or critical concerns, and major concerns were low and trending toward zero.
- `FAIL` — cycle budget was exhausted with blocking, critical, or significant major concerns still present.
