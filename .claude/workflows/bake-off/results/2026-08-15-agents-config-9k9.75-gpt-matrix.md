# Bake-off result: `agents-config-9k9.75`, GPT-5.6 matrix (runs m2 + m2b)

Arms and first judging ran 2026-08-14 (run m2); three arms were re-run and the full
cohort re-judged 2026-08-15 (run m2b, workflow `wf_00955d27-8e3`) after m2's high-effort
arms turned out to be harness casualties, not model results — see Scoring below. Raw
evidence for both runs, including every diff, sanitized report, seat verdict, checker
and reconciliation output, and the blind label key, is retained in the experiment
scratch tree (git-ignored) under the run slugs agents-config-9k9.75/m2 and .../m2b.

## The challenge

Nine blind arms — gpt-5.6-luna, gpt-5.6-terra, and gpt-5.6-sol, each at low/medium/high
reasoning effort, run via `codex exec` — independently implemented the same pinned brief
used for run m1 (`agents-config-9k9.75`: bind an item's review-snapshot lifetime to its
PR cycle in `packages/grind`) against the same base `3490762a`, with the same
justification requirements and the same closure-less-enqueue, refold-floor, red-first,
and consumer-accounting acceptance criteria. Each arm worked in its own worktree; each
diff was audited, gated, and sanitized for blind judging.

## Eval criteria — what is unusual here

Same rubric and process as m1: an AC-evidence audit before any quality scoring, five
pinned 0–5 quality axes, a quarantined checker seat running a per-task trap ledger
against imprecisions in the tracker item's own text, and a reconciliation stage that
re-verifies every seat's factual claims against the code and rules whether the majority
preference survives. Two things differ from m1 for this round:

- **A judge-only re-judge mode.** m2b re-scored the full nine-arm cohort from retained
  artifacts without re-running the six arms that didn't need it — same brief bytes, same
  panel shape, fresh verdicts.
- **A deterministic recovery ladder** for `codex exec` arms landed between the two runs
  (`agents-config-9k9.217.5`, merged the morning of m2b). m2's arms ran under the
  wrapper generation that preceded it.

## Models, all phases

| Phase | Model(s) |
|---|---|
| Arms (9, m2) | gpt-5.6-luna/terra/sol × low/medium/high (codex exec) |
| Arms re-run (3, m2b: N, O, Q) | gpt-5.6-luna/sol/terra, high effort (codex exec, deterministic recovery ladder) |
| Judge seats (3, blind, both runs) | sonnet high; opus high; gpt-5.6-sol high (via codex CLI) |
| Trap-ledger checker (both runs) | haiku, low effort |
| Reconciliation (both runs) | opus, high effort |

## Scoring

**m2's first pass was unanimous 3–0 for R (sol-medium)**, with "medium beats high in
every tier" as the apparent headline. That result does not stand: all three high-effort
arms (N=luna-high, O=sol-high, Q=terra-high) were harness casualties. N's gate log ran
`packages/installer`'s test suite instead of `packages/grind`'s — misdispatched onto
another arm's paths — and its diff is empty. O's and Q's gate logs both terminate mid
`make ci` with no exit recorded. All three arms' reports read "NO REPORT DELIVERED."
None of this reflects the models; it reflects the pre-ladder wrapper.

**m2b re-ran exactly those three arms** under the new deterministic ladder — same
labels, base, and brief bytes. Each completed in its first attempt with zero resumes:
N took 647s of wall clock (past the old wrapper's failure zone), O took 439s, Q took
130s. Q stopped deliberately with an empty diff: its report found AC7 (the never-reviewed
closure paths must show no anomalies) already true on the unmodified base, which it read
as contradicting AC9's demand for legitimate red-first failing-test evidence, and it
proposed the same design the seven implementing arms converged on without writing code.
It is recorded as no-contest, unmeasured by its own choice, not as a failure.

**The full nine-arm cohort was then re-judged fresh** by the same three seats (the six
untouched m2 artifact sets plus the three m2b re-runs). Preference was unanimous, 3–0,
for **O (sol-high)**. Reconciliation ruled the verified ledger `consistent` with that
preference; no inversion flag. Totals are each seat's five-axis sum (max 25), then the
three-seat mean:

| Rank | Contestant | sonnet-high | opus-high | sol-high | Mean |
|---|---|---|---|---|---|
| 1 | O — sol-high | 21 | 23 | 23 | 22.33 |
| 2 | R — sol-medium | 20 | 22 | 22 | 21.33 |
| 3 | N — luna-high | 20 | 19 | 21 | 20.00 |
| 4= | M — sol-low | 19 | 19 | 18 | 18.67 |
| 4= | L — terra-medium | 18 | 17 | 21 | 18.67 |
| 4= | S — luna-medium | 18 | 18 | 20 | 18.67 |
| 7 | T — terra-low | 20 | 18 | 16 | 18.00 |
| 8 | P — luna-low | 11 | 11 | 8 | 10.00 |
| — | Q — terra-high | — | — | — | no-contest |

Verified defect ledger, highlights (the reconciler applied each diff to an isolated
package copy and an unmodified base, folded a uniform behavioural probe through each,
and replayed each arm's new tests against the unmodified fold):

- **Vacuous projection assertions** — an index-0 read that resolves to a never-reviewed
  seeded item rather than the item under test — appear in six of the eight scored arms
  (L, M, N, R, S, T). **O is the only arm with no confirmed defect**: it addresses every
  projection by item id, its new tests all fail against the unmodified fold, and its
  written AC4 defense (which projections pair review data with parked state) matched the
  code on every checkable clause.
- **P carries the decisive-class defects**: its enqueue-path clear wipes a still-open
  PR's review even on a closure naming the wrong PR (which the base code's own docstring
  says should not apply), and its report overstates its red run by one failure.
- The checker's planted-probe ledger caught **arm M repeating the same false dashboard
  claim** (that the dashboard lane queue pairs parked items with review data, which it
  does not) in both the m2 and the m2b panels.
- Retained-arm score movement between the two panels, judging byte-identical artifacts,
  was mostly small but not uniformly so: five of the six retained arms (L, M, P, S, T)
  moved by at most 1.0 point on the three-seat mean; **R moved by 1.67** (23.0 → 21.33,
  falling on all three seats individually). This is larger than "at most ±1.0" and is
  reported here as a discrepancy against that framing rather than silently rounded down.

## Conclusions

1. **With adequate runway, effort scaling is positive within a model family on this
   task**: sol rises monotonically low→medium→high (M 18.67 → R 21.33 → O 22.33), and
   luna rises low→medium→high (P 10.00 → S 18.67 → N 20.00).
2. **Sol wins cross-tier at both measured tiers where a competitor exists**: sol-medium
   (R, 21.33) is the top medium-effort arm, and sol-high (O, 22.33) is the top measured
   high-effort arm — terra-high (Q) is unmeasured, so this is not a claim against it.
3. **m2's "medium beats high" pattern was the harness, not the models.** Once the three
   high-effort arms ran to completion, high beat medium within both measured families.

## Disclaimers

- **Runway inequality.** m2b's three re-run arms had a working deterministic recovery
  ladder (1200s watchdog per attempt, zero resumes needed) that m2's original run did
  not; the pre-ladder wrapper is what produced two mid-gate truncations and one
  misdispatch onto the wrong package's paths. The correction removes a harness defect,
  but the two groups of arms did not run under identical conditions.
- **terra-high (Q) remains unmeasured on this task.** It stopped on a principled
  objection rather than implementing, so the cross-tier and monotonic-scaling claims
  above cover sol and luna only.
- **Single-panel depth over nine arms**, same as m1's eleven-arm caveat: one verdict pass
  per cell (two, counting m2's and m2b's re-judge of the six untouched arms, whose
  overall preference and top defect findings held).
- **The sol-high judge seat (J3) scored a cohort that includes three sol arms** (M, R,
  O). Blind labels and neutral worktree names (`exp-9k9-75-m2-<label>`, no model
  identifiers) mitigate this, and J3's per-arm scores are not systematically inflated
  relative to J1/J2 for M, R, or O.
- **n=1 per arm, one task.** As with m1, this is a ranking on a sample produced primarily
  to exercise the workflow, not a routing law; effort-knob semantics may differ across
  model families and tasks.
