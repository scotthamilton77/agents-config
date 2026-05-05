---
name: ralf-implement
model: opus[1m]
effort: xhigh
argument-hint: "[target + DoD + context + optional max cycles]"
description: Explicit invocation only — iterative implementation with adversarial fresh-eyes cycles; inner-methodology only (no worktree or delivery ownership)
---

# ralf-implement

Iterative implementation methodology for code changes. This skill owns only the inner quality loop.

The caller must provide the target, Definition of Done, relevant context, and optional max cycle count. This skill owns no outer workflow state: no worktree setup, branch delivery, PR creation, tracker updates, or dispatch decisions.

## Required inputs

The invocation must include or already have in context:
- target task or implementation goal
- original specification or acceptance criteria
- Definition of Done
- relevant architectural context and quality commands
- optional max cycles, integer `1..20`

Fail fast when the target or Definition of Done is missing, the optional max cycle count is malformed or out of range, required referenced context cannot be read, or the project quality commands cannot be identified.

## Core invariants

1. **Iteration** — multi-pass, bounded by a cycle cap.
2. **Independence** — each fresh-eyes pass is a new subagent with no prior-cycle context.
3. **Adversarial posture** — each pass searches for missing, weak, or incorrect behavior.
4. **Convergence** — stop when findings are non-significant or cycle budget is exhausted.

## Cycle budget contract

Default cycle cap: `RALF_IMPLEMENT_DEFAULT_CYCLES=3`

The caller may pass an explicit max cycle count. If absent, use the default. Reject malformed, duplicate, or out-of-range cycle inputs instead of guessing.

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

This skill reports convergence state only. The caller decides whether to continue, defer, escalate, or accept with reservations.

## Severity rubric

- **Blocking** — prevents execution, validation, installation, or required delivery.
- **Critical** — violates explicit requirements, creates security/data-loss risk, or makes the implementation materially incorrect.
- **Major** — leaves important behavior, edge cases, tests, maintainability, or integration contracts incomplete.
- **Minor** — localized quality issue, documentation gap, naming issue, or small missing guard that does not threaten correctness.

## Output contract

Produce a structured report with:
- **Score:** `PASS`, `PASS_WITH_RESERVATIONS`, or `FAIL`
- **Score rationale:** one or two concrete sentences
- **Cycles run:** `<n>/<max>`
- **Severity counts:** blocking, critical, major, minor
- **Foreign-eyes status:** per cycle, including degraded Codex/Gemini runs
- **Changes applied:** significant fixes or completion work
- **Remaining concerns:** grouped by severity

Scoring:
- `PASS` — final cycle found no blocking, critical, or major quality concerns.
- `PASS_WITH_RESERVATIONS` — cycle budget was exhausted; final cycle found no blocking or critical concerns, and major concerns were low and trending toward zero.
- `FAIL` — cycle budget was exhausted with blocking, critical, or significant major concerns still present.
