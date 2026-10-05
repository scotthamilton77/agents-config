# Acceptance-criteria quality assessment: the evaluation contract

**Date:** 2026-09-29
**Status:** Draft child spec of `docs/specs/2026-09-18-acceptance-criteria-quality.md`,
slice S2 (quality assessment). Attacked once, on 2026-09-29, in an earlier
text. That round is not yet triaged.
**Work item:** `agents-config-9k9.405.10` (S2 feature), design child `agents-config-9k9.405.10.1`.
**Bounded by:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`.
**Charter:** `docs/specs/2026-07-21-harness-rework-way-forward.md`, decisions D2, D3, D5 and D7.

## Scope

S2 owns twenty-seven parent criteria. Six of them govern prompt emission and
the record check: ACQ-A20, A22, A23, A26, A28 and A29. Those six, and the
ownership of each rule by one lens, belong to the rule-ownership spec,
`docs/specs/2026-10-04-criteria-attack-rule-ownership.md`. The other
twenty-one, ACQ-A30 and ACQ-A31 among them, are claims about stochastic
lenses. The parent's Testing decisions require a fixed evaluation contract to
judge them. This spec fixes it.

Two more things are decided elsewhere. The arm experiments on
`agents-config-9k9.441` have their own spec,
`docs/specs/2026-10-01-criteria-attack-arm-experiments.md`. What a re-attack
round sees stays with `agents-config-9k9.442`.

## Current state

Verified at 38bda4ba.

- Lens front matter in `src/user/.claude/skills/ac-attack/lenses/` pins no
  model or effort.
- PR 791's body records the routing ACE-D6 adopts.
- No evaluation harness or case exists.
- The installer prunes `evals/` directories.

## Decisions

Rule ownership is ARO-D1 in the rule-ownership spec. It gives every rule
exactly one owning lens, so each case below has one lens. The IDs ACE-D1 and
ACE-A1 to ACE-A10 are not used here.

**ACE-D2 — A case is a document pair with a stated expectation.** Cases
live in `src/user/.claude/skills/ac-attack/evals/`, so they never deploy. The
manifest `evals/cases.json` gives each case:

- its ID;
- the parent criteria it serves;
- its rule;
- its lens;
- its defect site, which is a criterion ID, or `none` for an absence;
- a one-sentence detection statement;
- the source revision of any harvested document.

The directory `evals/cases/<id>/` holds `defective.md` and `control.md`. The
control is the defective document with its one defect corrected, and the two
differ in one contiguous hunk. One hunk does not prove one defect, so the
case's reviewer judges that. A control-only case has no defective document and
no site.

This settles two questions left open on `agents-config-9k9.441`: where cases
live, and how a case states its expectation. They are settled here because the
scorer reads both.

**ACE-D3 — The catalogue follows the parent's own text.** A parent
criterion's "Given" clause is its case's defect. Its no-finding clause is one
of two things: the correction itself, or a feature present in both documents
outside the changed hunk. Every control run then tests it. A case's lens is
the owner ARO-D1 gives its rule.

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
dispatch of one lens over one document.

- A defective run detects when an objection cites the case's rule at the
  case's site. This is mechanical. An objection citing only the rule, or only
  the site, detects when the judge (ACE-D5) rules that it describes the
  detection statement. A case whose site is `none` always goes to the judge.
- A control run is silent unless the judge rules that one of its objections
  describes the detection statement. Only an objection citing the case's rule
  or its site goes to the judge. Any other objection leaves the run silent.
- A control run is empty when the lens reports `empty`, which ACQ-A27 needs.
- A P1 run passes when the judge rules that no objection demands criteria for
  the implementation the document describes. P1 runs all four lenses, since
  any of them could wrongly demand implementation criteria of it.

A missing report, or one whose every objection is malformed, is repeated at
most twice. A run still without a usable report, or holding an objection the
judge has not ruled on, leaves its case pending and the evaluation incomplete.
A pending case is never scored as a miss.

**ACE-D5 — A calibrated judge decides what the scorer cannot place.** The
judge is Claude Opus through the native Agent tool, with the prompt
`evals/judge.md`.

For a case it receives the case's rule text, its
detection statement and one objection. For P1 it receives one objection alone.
It never sees the lens, the model or the arm.

A judgment task counts only after calibration. The owner, Scott Hamilton,
labels twenty items for the task, and the judge must agree on eighteen. A
prompt revised after a failed calibration is calibrated on twenty new items.
The experiments' validity and ground-matching tasks are calibrated the same
way.

The twenty items for a case task include mechanical detections. A mechanical
detection can be false: an objection can cite the right rule at the right site
and describe something else. The owner's labels on those items are the check
on that.

Eighteen of twenty bounds disagreement with
one evaluator on one sample, and says nothing about documents unlike it.

The run record names the judge's resolved model ID. Two runs compare only
under one judge model ID.

**ACE-D6 — The evaluated configuration is the production configuration.**

| Lens | Transport | Model | Effort | Reads |
| --- | --- | --- | --- | --- |
| behavioural-outcome, obligation-reduction | Codex CLI | `gpt-6.1-sol` | high | its prompt only, from an empty directory |
| set-consistency, what-if | OpenRouter | `moonshotai/kimi-k3` | low | its prompt only, with no tools |

Evaluating another configuration would judge a panel nobody runs. Kimi K3
never runs at high effort.

A lens able to read the repository could read this catalogue, so every lens
reads only its prompt (charter D7).

A run on a substituted model or effort does not count. A down transport means
the evaluation waits.

**ACE-D7 — A case is locked on its own runs, and every run counts.** The unit
of evaluation is the case. An attempt plans five runs of each of its documents.
A case has two sides: its detection, judged on the defective runs, and its
control, judged on the control runs for silence.

- A case detects when at least four of its five defective runs detect.
- A case's control holds when at least four of its five control runs are silent.
- A side at three of five gets one retest of five more runs and passes at
  eight of the ten. No run is discarded. A side below three fails.
- A case is locked when it detects and its control holds. P1 is locked when
  at least four of its five panel runs pass, with the same retest.
- A lens passes ACQ-A27 when at least 80 percent of the control runs behind
  its cases' current locks, P1's included, are empty. That rate is pooled
  across the lens's cases, so it is no side and earns no retest.

A parent criterion passes only when every case serving it is locked. Requiring
every case to pass inside one run would fail a lens that is right nineteen
times in twenty about three times in four, on luck alone.

No rate is averaged across cases. The scorer also reports each lens's pooled
rates, which decide nothing.

With the retest, a lens detecting half the time passes a side with probability
0.20, and one detecting nine times in ten passes with 0.96. The thresholds sit
above the one baseline, PR 785's control false positive, on purpose.

Locking the whole catalogue from nothing plans 310 lens dispatches, 220 on
Codex, plus retests and ACE-D4's repeats. Any larger plan, an experiment's
included, needs the owner's approval before dispatch. The owner confirmed the
run counts and thresholds on `agents-config-9k9.453`, after a pilot in which a
Codex run took one to three minutes. Changing a threshold amends this spec,
and scored results keep their thresholds.

**ACE-D8 — A lock is tied to what produced it.** The planner writes an
attempt's plan before any dispatch. The plan fixes every dispatch, the
configuration, the thresholds and the cases. Every attempt is committed with
its reports under `evals/runs/<run-id>/`, whatever it shows.
That rests on the operator, since nothing sees a run nobody commits.

A lock records its case's fingerprint. The fingerprint is the digests of the
prompts emitted for the case's two documents, with ACE-D6's model and effort.
An emitted prompt holds the lens body, the shared template and the rules the
lens enforces, so a change to any of them changes the fingerprint. P1's
fingerprint covers all four lenses.

A lock is current while its fingerprint matches the tree. A change voids only
the locks whose fingerprint it alters, and only those cases run again.

A change to the judge prompt, the judge model or the scorer dispatches no
lens. The stored reports are rescored, and a lock stands when its case still
passes.

The planner refuses an attempt on a case whose current fingerprint has had its
attempt and its retest. A failed case is then answered only by changing
something.

"The evaluation of record" is the set of current locks.

**ACE-D9 — Comparison and the template gate.** An addition to the shared
attack template ships only with a whole-catalogue comparison reporting
`improves` against the template without it.

A change improves on its baseline over the same cases when two things hold.
Every case locked under the baseline is locked under the change. At least two
lenses gain a locked case.

A gain in one lens alone belongs in that lens's own prompt.

ACQ-A23 admits an addition that carries this spec's evaluation evidence. A
test pins the template's digest to a registry of comparison reports. The
registry's baseline entry is the current template.

## Acceptance criteria

"Passes" means passing under ACE-D4 and ACE-D7. A case passes in the
evaluation of record when it holds a current lock (ACE-D8). The emitter and
checker suites run under `make content-tests`.

- **ACE-A11** The case check refuses a catalogue with no case for a rule the
  standard holds, naming the rule.
- **ACE-A12** The case check refuses a catalogue missing a case ACE-D3 lists,
  naming the case.
- **ACE-A13** The case check refuses a pair case whose documents are missing,
  identical, or differ in more than one contiguous hunk, or whose rule its
  lens does not enforce, naming the case and the fault.
- **ACE-A14** Given fixture reports and verdicts, the scorer counts a detection
  for an objection citing the case's rule at its site, and for one citing only
  the rule or only the site that the judge matches to the detection statement.
  It counts no other objection, and passes a P1 run only when the judge rules
  no objection demands implementation criteria.
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
- **ACE-A50** Given fixture control reports and verdicts, the scorer counts a
  control run as not silent only when the judge matches one of its objections,
  citing the case's rule or its site, to the detection statement.

### Traceability

| Parent | Child criteria | Check |
| --- | --- | --- |
| ACQ-A1 to A10, A14 to A19, A21, A30, A31 | ACE-A25 to ACE-A41, ACE-A44, ACE-A45, as the catalogue's Child column maps | The scorer's report on the evaluation of record |
| ACQ-A24, apart from rule ownership | ACE-A11 to ACE-A21, ACE-A42, ACE-A46 to ACE-A50, and the cases ACE-A25 to ACE-A40, ACE-A44 and ACE-A45 score | Case check, scorer suite, scorer report |
| ACQ-A27 | ACE-A17, ACE-A43 | Scorer suite, scorer report |
| The template rule in the parent's S2 slice text | ACE-A22 to ACE-A24 | Scorer suite, emitter suite |

### What-if questions

For ACE-A25 to ACE-A45:

- A failure names the failing case.
- A missing report or verdict leaves the case pending (ACE-A19).
- An attempt beyond a fingerprint's attempt and retest is refused (ACE-A21).
- The empty question does not apply to a fixed document pair.

For ACE-A11 to ACE-A13:

- An empty catalogue fails ACE-A11.

For ACE-A14 to ACE-A20, and ACE-A50:

- Fixture reports are fixed, so empty does not apply.
- A missing input is ACE-A19.

A case's first attempt has no
predecessor (ACE-A21). A tree with no lock voids none (ACE-A47). Lock sets
sharing no case gain nothing, so the comparison names the missing gain. An
absent registry fails ACE-A24.

Every check is a read, so running it twice or with nothing changed answers the
same way.

## Ordered slice list

- **S2.2: Case check** (ACE-A11 to ACE-A13; ACE-D2). The `evals/cases.json`
  format, and `evals/check_cases.py` with its suite. Depends on the
  rule-ownership spec's S2.1.
- **S2.3: Planning, scoring and the judge** (ACE-A14 to ACE-A21, ACE-A46 to
  ACE-A50; ACE-D4 to ACE-D8). `evals/plan_run.py`, `evals/score.py` and `evals/judge.md`, their
  suites, and the detection and P1 calibration records. Depends on S2.2.
- **S2.4: Comparison and the template gate** (ACE-A22 to ACE-A24; ACE-D9). A
  comparison mode in `evals/score.py` and the registry test. Depends on S2.3.
- **S2.5: The catalogue** (ACE-D3). The documents in `evals/cases/`. Cases
  harvested on `agents-config-9k9.441` join in ACE-D2's format when they
  land, and this slice does not wait for them. Depends on S2.2.
- **S2.6: Lens mandates** (ACE-D9; ARO-D1). A baseline attempt on every case, then body
  revisions for the rules each lens gained, each shown by a lens-level
  comparison to regress no case. Depends on S2.3, S2.4 and S2.5.
- **S2.7: Evaluation of record** (ACE-A25 to ACE-A45; ACE-D7). The
  verification child for every review-outcome criterion, as ACQ-D2 requires.
  It stays open until every case holds a current lock. Depends on S2.6.

The arm-experiments spec runs its experiments with S2.3's scorer and judge.
They are not S2 slices.

## Continuations

- feat: AC evaluation S2.2: the case check (ACE-D2) — AC: ACE-A11, ACE-A12, ACE-A13; make content-tests exits 0.
- feat: AC evaluation S2.3: planning, scoring and the judge (ACE-D4 to ACE-D8) — AC: ACE-A14, ACE-A15, ACE-A16, ACE-A17, ACE-A18, ACE-A19, ACE-A20, ACE-A21, ACE-A46, ACE-A47, ACE-A48, ACE-A49, ACE-A50; make content-tests exits 0.
- feat: AC evaluation S2.4: comparison and the template gate (ACE-D9) — AC: ACE-A22, ACE-A23, ACE-A24; make content-tests exits 0.
- feat: AC evaluation S2.5: the catalogue (ACE-D3) — AC: the committed catalogue passes the case check; make content-tests exits 0.
- feat: AC evaluation S2.6: lens mandates (ACE-D9) — AC: a committed baseline attempt on every case, and a lens-level comparison per revised lens.
- feat: AC evaluation S2.7: evaluation of record, the verification child (ACE-D7) — AC: ACE-A25, ACE-A26, ACE-A27, ACE-A28, ACE-A29, ACE-A30, ACE-A31, ACE-A32, ACE-A33, ACE-A34, ACE-A35, ACE-A36, ACE-A37, ACE-A38, ACE-A39, ACE-A40, ACE-A41, ACE-A42, ACE-A43, ACE-A44, ACE-A45.

## Out of scope

- Rule ownership, and the suite criteria on prompt emission and the record
  check, which the rule-ownership spec holds.
- What a re-attack round sees (`agents-config-9k9.442`).
- ACQ-A11 and ACQ-A25, which the parent gives to S1, with the content-lint
  rule `agents-config-9k9.405.3` suggests for ACQ-A11.
- A spec-lint shape rule for artifact criteria, which that item records as not
  adopted.
- The attack record assembler.
- A scheduled check for a model that changes under an unchanged ID, which no
  fingerprint sees.
