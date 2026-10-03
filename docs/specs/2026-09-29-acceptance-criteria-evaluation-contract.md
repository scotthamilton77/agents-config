# Acceptance-criteria quality assessment: the evaluation contract

**Date:** 2026-09-29
**Status:** Draft child spec of `docs/specs/2026-09-18-acceptance-criteria-quality.md`,
slice S2 (quality assessment). Not yet attacked.
**Work item:** `agents-config-9k9.405.10` (S2 feature), design child `agents-config-9k9.405.10.1`.
**Bounded by:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`.
**Charter:** `docs/specs/2026-07-21-harness-rework-way-forward.md`, decisions D2, D3, D5 and D7.

## Scope

S2 owns twenty-seven parent criteria. Six govern prompt emission and the record
check (ACQ-A20, A22, A23, A26, A28, A29). The other twenty-one, ACQ-A30 and
ACQ-A31 among them, are claims about stochastic lenses, which the parent's Testing decisions require a fixed
evaluation contract to judge. This spec fixes it. The arm experiments on
`agents-config-9k9.441` have their own spec,
`docs/specs/2026-10-01-criteria-attack-arm-experiments.md`. This spec does not
decide what a re-attack round sees, which stays with `agents-config-9k9.442`.

## Current state

Verified at 38bda4ba. Lens front matter in `src/user/.claude/skills/ac-attack/lenses/`
pins no model or effort. PR 791's body records the routing ACE-D6 adopts. No
evaluation harness or case exists. The installer prunes `evals/` directories.

## Decisions

**ACE-D1 — Every rule has exactly one owning lens.** The lenses enforce these rules:

| Lens | Rules |
| --- | --- |
| behavioural-outcome | `observable-obligation`, `document-deliverable`, `one-obligation`, `verification-contract`, `human-measurement`, `human-judgment`, `pending-until-performed`, `stochastic-and-window` |
| obligation-reduction | `coverage`, `sufficiency`, `can-fail`, `has-basis`, `restraint` |
| set-consistency | `consistency`, `decision-closure`, `verified-premise` |
| what-if | `what-if-questions` |

Today no lens enforces `restraint`, `verified-premise` or the last four
behavioural-outcome rules. The checker refuses a ground outside its lens, so
ACQ-A24 cannot pass for those six rules. ACQ-D6 gives behavioural-outcome
checkability, so the verification rules go there. A duplicate or an
unsupported prescription discharges no obligation part of its own, which the
obligation-reduction inventory shows. A premise contradicted by evidence
inside the document is a contradiction, which set-consistency reads for. No
lens reads the repository. One owner per rule gives each case one lens.

**ACE-D2 — A case is a document pair with a stated expectation.** Cases live in
`src/user/.claude/skills/ac-attack/evals/`, so they never deploy. The manifest
`evals/cases.json` gives each case its ID, the parent criteria it serves, its
rule, its lens, its defect site (a criterion ID, or `none` for an absence), a
one-sentence detection statement, and the source revision of any harvested
document. `evals/cases/<id>/` holds `defective.md` and `control.md`. The
control is the defective document with its one defect corrected, differing in
one contiguous hunk. One hunk does not prove one defect, so the case's
reviewer judges that. A control-only case has no defective document or site.
This settles two open questions on `agents-config-9k9.441`, where cases live
and how a case states its expectation, because the scorer reads both.

**ACE-D3 — The catalogue follows the parent's own text.** A parent criterion's
"Given" clause is its case's defect. Its no-finding clause is either the
correction itself or a feature present in both documents outside the changed
hunk, and every control run then tests it.

| Case | Serves | Rule | Lens | Child |
| --- | --- | --- | --- | --- |
| C1 | ACQ-A1 | `observable-obligation` | behavioural-outcome | ACE-A25 |
| C2 | ACQ-A2 | `observable-obligation` | behavioural-outcome | ACE-A26 |
| C3 | ACQ-A3 | `decision-closure` | set-consistency | ACE-A27 |
| C4 | ACQ-A4 | `one-obligation` | behavioural-outcome | ACE-A28 |
| C5 | ACQ-A5 | `can-fail` | obligation-reduction | ACE-A29 |
| C6 | ACQ-A6 | `consistency` | set-consistency | ACE-A30 |
| C7 | ACQ-A7 | `coverage` | obligation-reduction | ACE-A31 |
| C8 | ACQ-A8; what-if "something missing" | `what-if-questions` | what-if | ACE-A32 |
| C9 | ACQ-A9, no verification contract | `verification-contract` | behavioural-outcome | ACE-A33 |
| C10 | ACQ-A10 | `restraint` | obligation-reduction | ACE-A34 |
| C11 | ACQ-A14 | `verified-premise` | set-consistency | ACE-A35 |
| C12 | ACQ-A15, an unspecified window | `stochastic-and-window` | behavioural-outcome | ACE-A36 |
| C13 | ACQ-A16 | `one-obligation` | behavioural-outcome | ACE-A37 |
| C14 | ACQ-A17, advisory findings only | `pending-until-performed` | behavioural-outcome | ACE-A38 |
| C15 | ACQ-A31, a human check on a mechanically checkable property | `verification-contract` | behavioural-outcome | ACE-A45 |
| C16 | ACQ-A18; research answer | `document-deliverable` | behavioural-outcome | ACE-A39 |
| C17 | ACQ-A19 | `has-basis` | obligation-reduction | ACE-A40 |
| C18 to C21 | what-if "fails", "empty or at a limit", "twice or at the same time", "again with nothing changed", one case each | `what-if-questions` | what-if | ACE-A42 |
| C22 | decision document | `document-deliverable` | behavioural-outcome | ACE-A42 |
| C23 | parent closed before its verification evidence | `one-obligation` | behavioural-outcome | ACE-A42 |
| C24 | unsupported implementation prescription | `restraint` | obligation-reduction | ACE-A42 |
| C25 | stochastic threshold chosen after its results | `stochastic-and-window` | behavioural-outcome | ACE-A42 |
| C26 | a plausible implementation passing every criterion while breaking an in-scope obligation | `sufficiency` | obligation-reduction | ACE-A42 |
| C27 | human measurement without a protocol | `human-measurement` | behavioural-outcome | ACE-A42 |
| C28 | ACQ-A30, a human observer named alone | `human-judgment` | behavioural-outcome | ACE-A44 |
| C29 | incomplete observation window | `stochastic-and-window` | behavioural-outcome | ACE-A42 |
| P1 | ACQ-A21: a spec-authoring document assessed on content, control only | none | full panel | ACE-A41 |

**ACE-D4 — Scoring separates detection from silence.** A run is one fresh
dispatch of one lens over one document. P1 runs all four lenses, since any of
them could wrongly demand implementation criteria of it.

- A defective run detects when an objection cites the case's rule and the
  judge (ACE-D5) rules that it describes the detection statement. Citing the
  rule and the site is necessary and not sufficient.
- A control run is silent when no objection cites the case's rule. This is
  mechanical, and an objection on another rule does not break it.
- A control run is empty when the lens reports `empty`, which ACQ-A27 needs.
- A P1 run passes when the judge rules that no objection demands criteria for
  the implementation the document describes.
- A missing report, or one whose every objection is malformed, is repeated at
  most twice. A run still without a usable report, or holding an objection the
  judge has not ruled on, leaves its case pending and the evaluation
  incomplete. A pending case is never scored as a miss.

**ACE-D5 — A calibrated judge decides detection.** The judge is Claude Opus
through the native Agent tool, with the prompt `evals/judge.md`. It receives
the case's rule text, its detection statement and one objection, or for P1
one objection alone. It never sees the lens, the model or the arm. A judgment
task counts only after the owner, Scott Hamilton, labels twenty items for it
and the judge agrees on eighteen. A prompt revised after a failed calibration
is calibrated on twenty new items. The experiments' validity and
ground-matching tasks are calibrated the same way. Eighteen of twenty bounds disagreement with
one evaluator on one sample, and says nothing about documents unlike it. The
run record names the judge's resolved model ID. Two runs compare only under
one judge model ID.

**ACE-D6 — The evaluated configuration is the production configuration.**

| Lens | Transport | Model | Effort | Reads |
| --- | --- | --- | --- | --- |
| behavioural-outcome, obligation-reduction | Codex CLI | `gpt-5.6-sol` | high | its prompt only, from an empty directory |
| set-consistency, what-if | OpenRouter | `moonshotai/kimi-k3` | low | its prompt only, with no tools |

Evaluating another configuration would judge a panel nobody runs. Kimi K3
never runs at high effort. A lens able to read the repository could read this
catalogue, so every lens reads only its prompt (charter D7). A run on a
substituted model or effort does not count, and a down transport means the
evaluation waits.

**ACE-D7 — A case is locked on its own runs, and every run counts.** The unit
of evaluation is the case. An attempt plans five runs of each of its documents.

- A case detects when at least four of its five defective runs detect.
- A case's control holds when at least four of its five control runs are silent.
- A side at three of five gets one retest of five more runs and passes at
  eight of the ten. No run is discarded. A side below three fails.
- A case is locked when it detects and its control holds. P1 is locked when
  at least four of its five panel runs pass, with the same retest.
- A lens passes ACQ-A27 when at least 80 percent of the control runs behind
  its cases' current locks, P1's included, are empty.

A parent criterion passes only when every case serving it is locked. Requiring
every case to pass inside one run would fail a lens that is right nineteen
times in twenty about three times in four, on luck alone. No rate is averaged
across cases. The scorer also reports each lens's pooled rates, which decide
nothing. With the retest, a lens detecting half the time passes a side with
probability 0.20, and one detecting nine times in ten with 0.96. The thresholds
sit above the one baseline, PR 785's control false positive, on purpose.
Locking the whole catalogue from nothing plans 310 lens dispatches, 220 on
Codex, plus retests and ACE-D4's repeats. Any larger plan, an experiment's
included, needs the owner's approval before dispatch. The counts are
provisional until the baseline observation on `agents-config-9k9.453`, and are
fixed before the first lock is recorded. Changing a threshold after that
amends this spec, and scored results keep their thresholds.

**ACE-D8 — A lock is tied to what produced it.** The planner writes an
attempt's plan before any dispatch, fixing every dispatch, the configuration,
the thresholds and the cases. Every attempt is committed with its reports
under `evals/runs/<run-id>/`, whatever it shows; that rests on the operator,
since nothing sees a run nobody commits. A lock records its case's
fingerprint: the digests of the prompts emitted for its two documents, with
ACE-D6's model and effort. An emitted prompt holds the lens body, the shared
template and the rules the lens enforces, so a change to any of them changes
the fingerprint. P1's fingerprint covers all four lenses. A lock is current
while its fingerprint matches the tree. A change voids only the locks whose
fingerprint it alters, and only those cases run again. A change to the judge
prompt, the judge model or the scorer dispatches no lens: the stored reports
are rescored, and a lock stands when its case still passes. The planner
refuses an attempt on a case whose current fingerprint has had its attempt and
its retest. A failed case is then answered only by changing something. "The
evaluation of record" is the set of current locks.

**ACE-D9 — Comparison and the template gate.** A change improves on its
baseline over the same cases when every case locked under the baseline is
locked under the change, and at least two lenses gain a locked case. An addition to the shared
attack template ships only with a whole-catalogue comparison reporting
`improves` against the template without it. A gain in one lens alone belongs
in that lens's own prompt. ACQ-A23 admits an addition that carries this
spec's evaluation evidence. A test pins the template's digest to
a registry of comparison reports, whose baseline entry is the current template.

## Acceptance criteria

"Passes" means passing under ACE-D4 and ACE-D7. A case passes in the
evaluation of record when it holds a current lock (ACE-D8). The emitter and
checker suites run under `make content-tests`.

- **ACE-A1** In the source tree, every rule ID the standard holds appears in
  exactly one lens's `enforces` list. The emitter suite fails, naming the
  rule, when a rule has no owning lens or two.
- **ACE-A2** The emitter suite fails when the lens registry holds any set other
  than behavioural-outcome, obligation-reduction, set-consistency and what-if.
- **ACE-A3** Each emitted prompt equals its lens's body plus the four shared
  contracts, byte for byte, under the existing prompt-composition test.
- **ACE-A4** Each emitted prompt carries exactly the rules its lens enforces,
  under the existing prompt-composition test.
- **ACE-A5** A lens naming a rule the standard lacks is refused as `no-lenses`
  with nothing written, under the existing emitter test.
- **ACE-A6** The record check refuses as `schema` an objection lacking its
  target, its ground's rule, or any scenario part.
- **ACE-A7** The record check refuses as `schema` an objection carrying a field
  outside the objection schema, such as a drafted criterion.
- **ACE-A8** The record check refuses an obligation-reduction report whose
  workings are missing or fail their schema, as `invalid-workings`.
- **ACE-A9** The record check refuses a report whose undischarged part has no
  objection naming it, as `unreported-residue`.
- **ACE-A10** The record check refuses a ground its lens does not enforce, as
  `ground-outside-lens`.
- **ACE-A11** The case check refuses a catalogue with no case for a rule the
  standard holds, naming the rule.
- **ACE-A12** The case check refuses a catalogue missing a case ACE-D3 lists,
  naming the case.
- **ACE-A13** The case check refuses a pair case whose documents are missing,
  identical, or differ in more than one contiguous hunk, or whose rule its
  lens does not enforce, naming the case and the fault.
- **ACE-A14** Given fixture reports and verdicts, the scorer counts a detection
  only for an objection citing the case's rule that the judge matches to the
  detection statement, and passes a P1 run only when the judge rules no objection demands
  implementation criteria.
- **ACE-A15** Given fixture reports, the scorer passes a case's detection at
  four detecting runs of five and, after a retest, at eight of ten. It fails
  it at seven of ten and at two of five.
- **ACE-A16** Given fixture reports, the scorer holds a case's control at four
  silent runs of five and, after a retest, at eight of ten. It fails it at
  seven of ten and at two of five.
- **ACE-A17** Given fixture reports, the scorer passes a lens on ACQ-A27 at 80
  percent empty control runs and fails it below.
- **ACE-A18** The scorer refuses a run whose recorded model, effort, transport
  or run count differs from ACE-D6 and ACE-D7, naming the difference.
- **ACE-A19** A planned run with no usable report after two repeats, or with an
  objection the judge has not ruled on, leaves its case pending, and the
  scorer reports the evaluation incomplete.
- **ACE-A20** The scorer refuses to score a judgment task whose calibration
  record shows fewer than eighteen agreements in twenty.
- **ACE-A21** The planner refuses an attempt on a case whose current
  fingerprint already has an attempt and its retest, naming the case.
- **ACE-A22** Given two fixture lock sets over the same cases, the comparison
  reports `improves` when every case locked in the first is locked in the
  second and at least two lenses gain a locked case. Otherwise it names the
  regressed case or the missing gain.
- **ACE-A23** The comparison refuses two lock sets that differ in ACE-D6's
  configuration or in judge model ID, or either of which holds a pending case,
  naming the reason.
- **ACE-A24** The emitter suite fails when the shared template's digest has no
  registry entry whose comparison report says `improves`, the baseline excepted.
- **ACE-A25** C1 passes in the evaluation of record.
- **ACE-A26** C2 passes in the evaluation of record.
- **ACE-A27** C3 passes in the evaluation of record.
- **ACE-A28** C4 passes in the evaluation of record.
- **ACE-A29** C5 passes in the evaluation of record.
- **ACE-A30** C6 passes in the evaluation of record.
- **ACE-A31** C7 passes in the evaluation of record.
- **ACE-A32** C8 passes in the evaluation of record.
- **ACE-A33** C9 passes in the evaluation of record.
- **ACE-A34** C10 passes in the evaluation of record.
- **ACE-A35** C11 passes in the evaluation of record.
- **ACE-A36** C12 passes in the evaluation of record.
- **ACE-A37** C13 passes in the evaluation of record.
- **ACE-A38** C14 passes in the evaluation of record.
- **ACE-A39** C16 passes in the evaluation of record.
- **ACE-A40** C17 passes in the evaluation of record.
- **ACE-A41** P1 passes in the evaluation of record.
- **ACE-A42** C18 to C27 and C29 pass in the evaluation of record, over a
  committed catalogue the case check accepts.
- **ACE-A43** Every lens passes ACQ-A27 in the evaluation of record.
- **ACE-A44** C28 passes in the evaluation of record.
- **ACE-A45** C15 passes in the evaluation of record.
- **ACE-A46** The planner plans a retest only for a side at three of five, and
  the scorer judges a retested side on all ten of its runs.
- **ACE-A47** Given locks and a tree in which one case's document or one
  lens's emitted prompt has changed, the scorer reports as void exactly the
  locks whose fingerprint changed, naming each.
- **ACE-A48** Given stored reports and a changed judge prompt or scorer, the
  scorer rescores them with no lens dispatch planned, and keeps a lock only
  when its case still passes.
- **ACE-A49** The scorer's report states each lens's pooled detection and
  silence rates over the runs behind its current locks.

### Traceability

| Parent | Child criteria | Check |
| --- | --- | --- |
| ACQ-A1 to A10, A14 to A19, A21, A30, A31 | ACE-A25 to ACE-A41, ACE-A44, ACE-A45, as the catalogue's Child column maps | The scorer's report on the evaluation of record |
| ACQ-A20 | ACE-A6, ACE-A7 | Checker suite |
| ACQ-A22 | ACE-A2 | Emitter suite |
| ACQ-A23 | ACE-A3 | Emitter suite, existing test |
| ACQ-A24 | ACE-A1, ACE-A11 to ACE-A21, ACE-A42, ACE-A46 to ACE-A49, and the cases ACE-A25 to ACE-A40, ACE-A44 and ACE-A45 score | Emitter suite, case check, scorer suite, scorer report |
| ACQ-A26 | ACE-A4, ACE-A5 | Emitter suite, existing tests |
| ACQ-A27 | ACE-A17, ACE-A43 | Scorer suite, scorer report |
| ACQ-A28 | ACE-A8, ACE-A9 | Checker suite, existing tests |
| ACQ-A29 | ACE-A10 | Checker suite, existing test |
| The template rule in the parent's S2 slice text | ACE-A22 to ACE-A24 | Scorer suite, emitter suite |

### What-if questions

For ACE-A25 to ACE-A45, a failure names the failing case, a missing report or
verdict leaves it pending (ACE-A19), an attempt beyond a fingerprint's attempt
and retest is refused (ACE-A21), and the empty question does not apply to a
fixed document pair. For
ACE-A1 to ACE-A13, an empty registry and an absent standard are the existing
`no-lenses` and `no-standard` refusals, and an empty catalogue fails ACE-A11.
For ACE-A14 to ACE-A20, fixture reports are fixed, so empty does not apply,
and a missing input is ACE-A19. A case's first attempt has no predecessor
(ACE-A21), and a tree with no lock voids none (ACE-A47). Lock sets sharing no
case gain nothing, so the comparison names the
missing gain, and an absent registry fails ACE-A24. Every check is a read, so
running it twice or with nothing changed answers the same way.

## Ordered slice list

- **S2.1: Rule ownership and the attack surface** (ACE-A1 to ACE-A10; ACE-D1).
  Reassign `enforces` in `lenses/*/prompt.md`, and add the new tests to
  `emit_prompts_test.py` and `check_record_test.py`. Depends on S1, landed.
- **S2.2: Case check** (ACE-A11 to ACE-A13; ACE-D2). The `evals/cases.json`
  format, and `evals/check_cases.py` with its suite. Depends on S2.1.
- **S2.3: Planning, scoring and the judge** (ACE-A14 to ACE-A21, ACE-A46 to
  ACE-A49; ACE-D4 to ACE-D8). `evals/plan_run.py`, `evals/score.py` and `evals/judge.md`, their
  suites, and the detection and P1 calibration records. Depends on S2.2.
- **S2.4: Comparison and the template gate** (ACE-A22 to ACE-A24; ACE-D9). A
  comparison mode in `evals/score.py` and the registry test. Depends on S2.3.
- **S2.5: The catalogue** (ACE-D3). The documents in `evals/cases/`. Cases
  harvested on `agents-config-9k9.441` join in ACE-D2's format when they
  land, and this slice does not wait for them. Depends on S2.2.
- **S2.6: Lens mandates** (ACE-D1, ACE-D9). A baseline attempt on every case, then body
  revisions for the rules each lens gained, each shown by a lens-level
  comparison to regress no case. Depends on S2.3, S2.4 and S2.5.
- **S2.7: Evaluation of record** (ACE-A25 to ACE-A45; ACE-D7). The
  verification child for every review-outcome criterion, as ACQ-D2 requires.
  It stays open until every case holds a current lock. Depends on S2.6.

The arm-experiments spec runs its experiments with S2.3's scorer and judge.
They are not S2 slices.

## Continuations

- feat: AC evaluation S2.1: rule ownership and the attack surface (ACE-D1) — AC: ACE-A1, ACE-A2, ACE-A3, ACE-A4, ACE-A5, ACE-A6, ACE-A7, ACE-A8, ACE-A9, ACE-A10; make content-tests exits 0.
- feat: AC evaluation S2.2: the case check (ACE-D2) — AC: ACE-A11, ACE-A12, ACE-A13; make content-tests exits 0.
- feat: AC evaluation S2.3: planning, scoring and the judge (ACE-D4 to ACE-D8) — AC: ACE-A14, ACE-A15, ACE-A16, ACE-A17, ACE-A18, ACE-A19, ACE-A20, ACE-A21, ACE-A46, ACE-A47, ACE-A48, ACE-A49; make content-tests exits 0.
- feat: AC evaluation S2.4: comparison and the template gate (ACE-D9) — AC: ACE-A22, ACE-A23, ACE-A24; make content-tests exits 0.
- feat: AC evaluation S2.5: the catalogue (ACE-D3) — AC: the committed catalogue passes the case check; make content-tests exits 0.
- feat: AC evaluation S2.6: lens mandates (ACE-D1, ACE-D9) — AC: a committed baseline attempt on every case, and a lens-level comparison per revised lens.
- feat: AC evaluation S2.7: evaluation of record, the verification child (ACE-D7) — AC: ACE-A25, ACE-A26, ACE-A27, ACE-A28, ACE-A29, ACE-A30, ACE-A31, ACE-A32, ACE-A33, ACE-A34, ACE-A35, ACE-A36, ACE-A37, ACE-A38, ACE-A39, ACE-A40, ACE-A41, ACE-A42, ACE-A43, ACE-A44, ACE-A45.

## Out of scope

What a re-attack round sees (`agents-config-9k9.442`). ACQ-A11 and ACQ-A25,
which the parent gives to S1, with the content-lint rule `agents-config-9k9.405.3`
suggests for ACQ-A11. A spec-lint shape rule for artifact criteria, which that
item records as not adopted. The attack record assembler. A scheduled check
for a model that changes under an unchanged ID, which no fingerprint sees.
