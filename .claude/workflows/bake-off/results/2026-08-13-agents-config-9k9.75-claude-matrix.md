# Bake-off result: `agents-config-9k9.75`, full Claude matrix (run m1)

Arms ran 2026-08-12; judging completed 2026-08-13. Workflow runs `wf_9743cf3b-03b`
(arms + one surviving judge seat) and `wf_b2232d16-b9a` (judge re-seat after an API
outage — see the incident note). Raw evidence, including every diff, sanitized report,
seat verdict, and the blind label key, is retained in the experiment scratch tree
(git-ignored) under the run slug agents-config-9k9.75/m1.

## The challenge

Eleven blind arms independently implemented the same pinned brief against base
`3490762a`: bound the lifetime of an item's review snapshot across PR cycles in
`packages/grind` — a real defect (`agents-config-9k9.75`) whose fold retained a closed
PR's review verdict until the next review overwrote it. The brief pins 12 acceptance
criteria (both closure paths, an explicitly contested parked-route trade-off the arm
must decide *and defend*, closure-less enqueue, refold floor, red-first test evidence,
consumer accounting, `make ci` green, commit hygiene) while leaving the design choice
free. Each arm worked in its own worktree from the same base; each diff was audited,
gated, and sanitized for blind judging.

## Eval criteria — what is unusual here

- **A green gate proves the arm's tests pass, not that the criteria are met.** The
  rubric's Phase 1 is an AC evidence audit: judges derive each criterion's claim-space
  from the code themselves and treat the arm's tests, comments, and docstrings as
  advocacy. Verdicts are pinned / partially-pinned / unpinned per criterion, before any
  quality scoring.
- Five pinned quality axes (correctness robustness, test quality, decision quality,
  fit and scope, engineering quality), 0–5, exact JSON keys enforced by schema.
- A **quarantined checker seat** applies a per-task trap ledger (three planted factual
  probes derived from imprecisions in the tracker item's own text); main judge seats
  never see the ledger.
- A **reconciliation stage** re-verifies every factual claim from every seat against
  the code, applies each finding to every arm uniformly, and rules whether the
  majority preference survives the verified ledger; a contradiction raises a flag for
  human review and never silently flips the result.
- The rubric was validated before this run on a known-answer contest (an
  independently established verdict and decisive defect the panel had to reproduce
  blind). This run is its first live contest.

## Models, all phases

| Phase | Model(s) |
|---|---|
| Arms (11) | sonnet medium/high/xhigh; opus low/medium/high/xhigh; fable low/medium/high/xhigh |
| Worktree resets, audits, codex transport wrappers | haiku, low effort |
| Report sanitizers (blinding) | sonnet, low effort |
| Judge seats (3, blind) | sonnet high; opus high; GPT-5.6 sol high (via codex CLI) |
| Trap-ledger checker | haiku, low effort |
| Reconciliation | opus, high effort |

All 11 arms committed work and exited the `make ci` gate green. One arm (sonnet-high)
produced a green implementation but delivered no report, failing the four
justification-class criteria outright.

## Scoring

Preference: **unanimous, 3–0, for opus-xhigh.** Reconciliation ruled the verified
ledger `consistent` with that preference; no inversion flag. Totals below are each
seat's five-axis sum (max 25), then the three-seat mean.

| Rank | Contestant | sonnet-high | opus-high | sol-high | Mean |
|---|---|---|---|---|---|
| 1 | opus-xhigh | 24 | 25 | 24 | 24.3 |
| 2 | opus-high | 24 | 25 | 23 | 24.0 |
| 3 | fable-xhigh | 22 | 22 | 23 | 22.3 |
| 4 | opus-medium | 24 | 22 | 18 | 21.3 |
| 5= | fable-medium | 20 | 21 | 20 | 20.3 |
| 5= | opus-low | 23 | 20 | 18 | 20.3 |
| 7 | fable-low | 19 | 20 | 20 | 19.7 |
| 8 | sonnet-medium | 19 | 19 | 20 | 19.3 |
| 9 | fable-high | 21 | 21 | 13 | 18.3 |
| 10 | sonnet-xhigh | 11 | 15 | 14 | 13.3 |
| 11 | sonnet-high | 12 | 14 | 13 | 13.0 |

Verified defect ledger, highlights (31 symmetrized findings; the reconciler re-applied
every diff to a pristine package copy and folded a ten-route probe history through
each, so these are measurements, not readings):

- **sonnet-xhigh, decisive:** on `pr_closed(next="parked")` followed by a closure-less
  `item_enqueued`, a stale closed-PR verdict rides back into active work and reaches
  the dashboard — plus a docstring asserting the missed route safe. The same defect
  family, with the same confident-false-documentation signature, appeared in a
  sonnet-medium arm during the framework's earlier shake-down on this task.
- **sonnet-high:** no report delivered; judged on the diff alone.
- **opus-low and opus-medium:** both gave a false answer to the criterion-mandated
  projection investigation (claiming the handoff projection skips parked items; it
  does not).
- **fable-medium:** one false supporting claim; **opus-high:** one imprecise
  replacement comment. **fable-high** uniquely guards the one route outside the
  brief's objective (ruled a unique advantage, not a defect elsewhere).
- Checker matrix: zero cells where an arm repeated a planted false claim; arms split
  only on catching vs staying silent about the third probe.

## Conclusions

1. **Opus scaled monotonically with reasoning effort** (xhigh > high > medium > low),
   and opus-low outranked every sonnet arm.
2. **fable-xhigh did not beat opus-high** on this implementation task — third place,
   clear of the midfield, no premium over opus here.
3. **Sonnet underperformed at every effort tier on this task class**, and twice
   produced the same defect family with false documentation asserting the missed
   route safe (medium in the shake-down, xhigh here).

## Disclaimers

- **n=1 per cell, single task.** One run per arm on one implementation task. This is
  a ranking on a sample, produced primarily to prove the workflow end to end — not a
  routing law. Effort-knob semantics may also differ across model families.
- **Anthropic-heavy throughout.** All 11 arms are Claude models (the GPT-5.6 arms are
  a planned separate round), and two of three judge seats are Anthropic models. The
  cross-vendor check is a single GPT seat plus the reconciliation stage.
- **Incident:** an API outage killed both Anthropic judge seats mid-verdict on the
  first pass. They were re-seated in a recovery run on the same models, efforts, and
  byte-identical instructions, over unchanged artifacts; the sol seat and checker
  verdicts are from the original pass. The re-seated panel had no access to the
  original seats' partial work.
- The sonnet-high arm's missing report may reflect a delivery failure rather than
  model capability; its scores are dominated by the four justification criteria it
  therefore failed.
