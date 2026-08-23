# Bake-off final report: what the model×effort experiment measured

Written 2026-08-23, closing the experiment spike. This entry synthesizes every run to
date — two on the implementation task (`agents-config-9k9.75`), one on the design task
(`agents-config-9k9.145.1`), one on a second design-class task (the grill-master role
re-examination) — and states what routing guidance the evidence supports, what it does
not, and where the numbers came from.

For the two `9k9.75` runs the primary sources are the results entries dated 2026-08-13
and 2026-08-15 in this directory; their numbers are quoted here, not re-derived. The two
design-class runs have no prior results entry, so this report is their first.

## The runs

### 1. `agents-config-9k9.75` m1 — full Claude matrix (implementation class)

Arms ran 2026-08-12, judged 2026-08-13. Workflows `wf_9743cf3b-03b` (arms plus one
surviving judge seat) and `wf_b2232d16-b9a` (judge re-seat after an API outage). Base
`3490762a`. Eleven arms: sonnet medium/high/xhigh; opus low/medium/high/xhigh; fable
low/medium/high/xhigh. Panel: sonnet-high, opus-high, GPT-5.6 sol-high (codex).

All 11 arms committed and exited `make ci` green. Preference **unanimous 3–0 for
opus-xhigh**; reconciliation ruled the verified ledger consistent, no inversion flag.
Three-seat mean of the five-axis sum (max 25):

| Rank | Arm | Mean |
|---|---|---|
| 1 | opus-xhigh | 24.3 |
| 2 | opus-high | 24.0 |
| 3 | fable-xhigh | 22.3 |
| 4 | opus-medium | 21.3 |
| 5= | fable-medium | 20.3 |
| 5= | opus-low | 20.3 |
| 7 | fable-low | 19.7 |
| 8 | sonnet-medium | 19.3 |
| 9 | fable-high | 18.3 |
| 10 | sonnet-xhigh | 13.3 |
| 11 | sonnet-high | 13.0 |

**Per-arm cost: unavailable.** The usage collector (`collect_usage.py`) did not exist
when this run executed; no usage or cost record was retained for m1, and none is
reconstructed here.

*What it can tell us:* on one real implementation defect, opus scaled monotonically with
effort, opus-low outranked every sonnet arm, and fable-xhigh carried no premium over
opus-high. *What it cannot:* nothing about price, nothing about GPT models, and nothing
about repeatability — n=1 per cell. The sonnet-high arm delivered no report, so its score
may be a delivery failure rather than capability.

### 2. `agents-config-9k9.75` m2 + m2b — GPT-5.6 matrix (implementation class)

Arms and first judging 2026-08-14 (m2); three arms re-run 2026-08-15 (m2b, workflow
`wf_00955d27-8e3`) and the full cohort re-judged fresh (workflow `wf_fe703d90-a79`). Same
base `3490762a`, same brief bytes, same panel shape as m1. Nine arms: gpt-5.6
luna/terra/sol × low/medium/high, via `codex exec`.

m2's first-pass headline ("medium beats high in every tier", unanimous for sol-medium)
**does not stand**: all three high-effort arms were harness casualties of the pre-ladder
codex wrapper — one misdispatched onto another package's paths with an empty diff, two
truncated mid-`make ci`. m2b re-ran exactly those three under the deterministic recovery
ladder; each completed on its first attempt with zero resumes (luna-high 647s, sol-high
439s, terra-high 130s). terra-high stopped deliberately with an empty diff, reading AC7 as
already true on the unmodified base and therefore contradicting AC9's demand for red-first
evidence; it is recorded as no-contest, not a failure.

The re-judged cohort: preference **unanimous 3–0 for sol-high**, reconciliation
consistent, no inversion flag. Three-seat mean (max 25):

| Rank | Arm | Mean |
|---|---|---|
| 1 | sol-high | 22.33 |
| 2 | sol-medium | 21.33 |
| 3 | luna-high | 20.00 |
| 4= | sol-low | 18.67 |
| 4= | terra-medium | 18.67 |
| 4= | luna-medium | 18.67 |
| 7 | terra-low | 18.00 |
| 8 | luna-low | 10.00 |
| — | terra-high | no-contest |

**Per-arm cost: unavailable** for m2 and m2b, same reason as m1.

*What it can tell us:* with adequate runway, effort scales positively inside a GPT family
(sol 18.67 → 21.33 → 22.33; luna 10.00 → 18.67 → 20.00), and sol wins cross-tier at both
measured tiers. sol-high was the only arm in the cohort with no confirmed defect. *What it
cannot:* terra-high is unmeasured, the two arm groups did not run under identical harness
conditions, and — because there is no cost record — this run says nothing about
price-per-quality against the Claude matrix.

### 3. `agents-config-9k9.145.1` m1 — 15-arm design matrix (design class)

The design-class contest: author the S8 child spec carving `packages/prgroom`, a
document-only deliverable gated by `make spec-lint`. Base `8799924e`. Two arms fired solo
first (luna-medium 2026-08-22, sonnet-medium later that day), the remaining thirteen in
one run `wf_819fef48-d47` on 2026-08-23, with `wf_bf45bd53-c93` carrying one arm. The
whole 15-arm field was then judged in one pass by the three-seat panel via judge-only
mode: `wf_51c6970b` — J1 sonnet-high, J2 opus-high, J3 codex gpt-5.6-sol-high, plus the
trap-ledger checker; reconciliation off, escalation off. Axes for this class are factual
grounding, decomposition quality, criteria convertibility, decision quality, fit and scope
(0–5 each, max 25).

All 15 arms delivered a diff and a report. Preference **unanimous 3–0 for fable-xhigh**;
all three seats ranked it first. No arm was disqualified or dropped.

| Rank | Arm | J1 sonnet-high | J2 opus-high | J3 sol-high | Mean | Cost |
|---|---|---|---|---|---|---|
| 1 | fable-xhigh | 25 | 25 | 17 | 22.33 | $35.51 |
| 2 | fable-medium | 25 | 21 | 13 | 19.67 | $17.11 |
| 3 | sol-medium | 23 | 20 | 11 | 18.00 | $4.85 |
| 4= | opus-xhigh | 22 | 18 | 13 | 17.67 | $13.20 |
| 4= | opus-high | 20 | 22 | 11 | 17.67 | $10.07 |
| 6= | opus-medium | 19 | 17 | 12 | 16.00 | $7.83 |
| 6= | sol-high | 19 | 17 | 12 | 16.00 | $6.03 |
| 8 | fable-high | 19 | 16 | 11 | 15.33 | $23.04 |
| 9 | sonnet-xhigh | 17 | 15 | 11 | 14.33 | $6.60 |
| 10 | terra-high | 17 | 14 | 11 | 14.00 | $1.18 |
| 11 | luna-high | 14 | 15 | 11 | 13.33 | $0.34 |
| 12 | sonnet-medium | 14 | 14 | 11 | 13.00 | $3.42 |
| 13 | sonnet-high | 13 | 15 | 10 | 12.67 | $3.09 |
| 14 | luna-medium | 12 | 12 | 10 | 11.33 | $0.05 |
| 15 | terra-medium | 7 | 11 | 9 | 9.00 | $0.57 |

Costs are the retained per-arm usage record for this run, priced against the price table
verified 2026-08-22. Total arm spend: **$132.9**.

Two structural readings the table supports. First, the J3 seat scored on a visibly
compressed range (9–17, against J1's 7–25) while producing the same top pick — cardinal
scores are not comparable across seats, ordinal agreement is what carries. Second, the
effort knob is **not** monotonic here: fable-medium (19.67) beat fable-high (15.33) by a
wide margin while fable-xhigh won outright, and opus-xhigh tied opus-high exactly.

*What it can tell us:* on one document-authoring task with an inventory-plus-decisions
contract, the top tier at maximum effort wins, and it costs roughly 7× the third-place
arm. *What it cannot:* n=1 per cell again, one task, and one gate (`spec-lint`) that is
far weaker evidence than a real test suite — a design deliverable's quality is almost
entirely in the judged content.

An earlier attempt at this run, `/tmp/bakeoff-9k9.145.1-m1-FAILED-nobrief/`, is a harness
casualty: the arms ran without the brief in place. It is not evidence and no number here
comes from it.

### 4. gm-role m1 — grill-master role re-examination (design class)

Run 2026-08-23, workflow `wf_f6b3f882-4e6`, base `26f15294`, gate `make spec-lint`. Three
arms only — the top three combinations from the 145.1 matrix, run as a confirmation on a
different design task: fable-xhigh, fable-medium, sol-medium. The deliverable was a ruling
on what the grilling-UI backend's agents are, with 14 acceptance criteria.

| Arm | Combination | J1 sonnet-high | J2 opus-high | J3 sol-high | ACs met | Cost |
|---|---|---|---|---|---|---|
| S | fable-xhigh | 1st | 1st | 2nd | 14/14 | $24.49 |
| R | sol-medium (codex) | 2nd | 2nd | 1st | 14/14 | $2.30 |
| T | fable-medium | 3rd | 3rd | 3rd | 13/14 | $14.17 |

**Winner: fable-xhigh on a 2/3 preference majority** — the same combination that won the
15-arm matrix, on a different design task. All three arms delivered, all gated green, and
all three independently reached the same core ruling. Total arm spend $40.96. Checker
(3 probes): sol-medium caught 3/3, the two fable arms caught 2 and stayed silent on 1; no
arm repeated a planted false claim.

**Judge-seat incident.** J1 was configured as an OpenRouter seat on `qwen/qwen3.8-27b`
with a sonnet fallback. The qwen sessions never converged — 16–40 minutes per audit,
0-byte results — and two of its transport agents timed out and **fabricated well-formed
verdicts** that parsed as valid and slipped past the seat-wide fallback, which keys on
launcher refusal or unparseable output rather than on authenticity. That seat's own output
is void; the J1 column above is the clean sonnet-high re-run. Nothing in this report rests
on a qwen verdict.

*What it can tell us:* the 145.1 winner replicates on a second, unrelated design task, and
does so against the same two runners-up — which is the strongest single piece of evidence
in the whole experiment, because it is the only cross-task replication. *What it cannot:*
three arms, one run each, and only the top three combinations were entered, so it re-tests
a ranking rather than establishing one.

## What the evidence supports, per task class

**For implementation tasks — a defect fix in a real package, gated by a real test suite —
the measured pick is opus at xhigh effort.** It won the Claude matrix unanimously (24.3,
ahead of opus-high at 24.0 and fable-xhigh at 22.3), and effort scaled monotonically within
opus. fable-xhigh bought nothing over opus-high on this class. Sonnet underperformed at
every effort tier, and twice produced the same defect family with documentation asserting
the missed route safe. Among GPT models on the same task, the measured pick is **sol at
high effort** (22.33), with sol-medium (21.33) close behind.

**For design tasks — authoring a spec or a ruling document, where the gate checks form and
the judgment is in the content — the measured pick is fable at xhigh effort.** It won the
15-arm matrix unanimously (22.33 against fable-medium's 19.67 and sol-medium's 18.00) and
then won again on an unrelated design task against those same two runners-up. **The
cost-effective pick on this class is sol-medium**: third on the matrix and second on the
gm-role run (where one seat put it first), at $4.85 against
fable-xhigh's $35.51 on the matrix, and at $2.30 against $24.49 on the gm-role run — about
one-tenth the price for roughly 80% of the winner's score. Note also that raising fable
from medium to high effort *lowered* its score on the matrix (19.67 → 15.33); only xhigh
paid.

**Across both classes:** where a Claude and a GPT arm land near each other on quality, the
GPT arm is between 5× and 10× cheaper. Cost — not token count — is the comparable axis, and
the design matrix is the only run where the full price picture exists.

## What the evidence does not support

- **No claim of repeatability.** n=1 per arm in every run. Each ranking is one sample; no
  arm was ever run twice on the same brief to measure its own variance.
- **No claim about terra at high effort on the implementation task.** It stopped on a
  principled objection rather than implementing, and is recorded as no-contest. The GPT
  cross-tier and monotonic-scaling claims cover sol and luna only.
- **No cross-model-family effort semantics.** "xhigh" on a Claude model and "high" on a
  GPT model are different knobs; nothing here calibrates them against each other.
- **No cardinal comparison across judge seats.** Seat score ranges differ sharply — on the
  design matrix J3 used 9–17 where J1 used 7–25. Cross-panel scoring is cardinally noisy
  and only ordinally stable; a 1-point mean gap between adjacent arms is not a result. On
  the implementation task, one arm's mean moved 1.67 points between two panels judging
  byte-identical artifacts.
- **No price-per-quality claim on the implementation class.** Neither m1 nor m2/m2b
  retained a usage record, so every implementation-class cost statement is unavailable
  rather than merely uncertain.
- **No claim about the top tier at maximum effort on implementation.** fable-xhigh ran and
  placed third; but no Claude arm above opus-xhigh was entered, and terra-high was
  deliberately never re-run to completion on that task.
- **No claim that any class outside these two behaves the same way.** Review, diagnosis,
  refactoring, research: unmeasured. So is any task longer than a single agent session.
- **No claim from a single run per class beyond ordering.** The design-class guidance rests
  on two runs, one of which entered only three arms; the implementation-class guidance
  rests on two runs, one per vendor, that were never scored against each other directly.
- **Nothing rests on the void judge seat.** The OpenRouter qwen seat produced no usable
  audit and two fabricated verdicts, all discarded.

## Standing reminder — the fair-comparison gate

From Scott, 2026-08-15, to be honoured by the next run:

> Once the bake-off is stable, run it against a task whose inputs pass **all** gates going
> in — a brief with no internal contradictions — so the comparison is fair. The input grill
> for the next task class must include an explicit gate-check that **no AC pair is mutually
> unsatisfiable.**

The occasion for this is concrete: the m2b terra-high arm stopped without implementing
because it read AC7 (never-reviewed closure paths show no anomalies — already true on the
unmodified base) as contradicting AC9's demand for legitimate red-first failing-test
evidence. That arm was tripped by the framing, not by the task, and the run lost a cell it
had already paid for. An arm that stops on a brief defect is unmeasured, and an unmeasured
arm is the most expensive kind.

## Provenance

Every number above traces to a file that was read for this report.

- The m1 and m2/m2b tables, workflow ids, base commit, defect-ledger findings and
  disclaimers: the results entries dated 2026-08-13 and 2026-08-15 in this directory,
  quoted rather than re-derived.
- The 15-arm design matrix scores, per-seat orderings, unanimous preference, and the
  absence of disqualifications: the panel result JSON retained under the run slug
  `agents-config-9k9.145.1/m1` in the experiment scratch tree; means are the arithmetic
  mean of the three seats' five-axis sums, computed from that file.
- The design matrix's label→combination mapping, base, panel composition and gate: the run's
  label key, retained beside the panel result.
- Design-matrix per-arm costs: the retained usage record for that run, which prices each
  arm against the price table verified 2026-08-22.
- The gm-role standings, checker results, judge-seat incident and cost figures: that run's
  results file and its usage record, retained under the run slug `gm-role/m1`.
- The standing reminder and the m2b AC7/AC9 stop: the experiment's project memory entry,
  cross-checked against the 2026-08-15 results entry.

**Gaps, stated rather than filled.** No usage or cost record exists for the three
implementation-class runs (m1, m2, m2b); those rows read "unavailable" and nothing is
estimated. The cold-start handoff `bake-off-handoff.md` referenced at the project root is
not present in the working tree, so nothing here cites it. The failed no-brief attempt at
the design matrix is named as a harness casualty and contributes no numbers.
