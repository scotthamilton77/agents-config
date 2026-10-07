# Acceptance-criteria quality assessment: the evaluation contract

**Date:** 2026-09-29
**Status:** Draft child spec of `docs/specs/2026-09-18-acceptance-criteria-quality.md`,
slice S2 (quality assessment). Attacked on 2026-09-29 and, in this text, on
2026-10-07; the record beside this file is the second round's.
**Work item:** `agents-config-9k9.405.10` (S2 feature), design child `agents-config-9k9.405.10.1`.
**Bounded by:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`.
**Charter:** `docs/specs/2026-07-21-harness-rework-way-forward.md`, decisions D2, D3, D5 and D7.

## Scope

S2 owns twenty-seven parent criteria. Six of them govern prompt emission and
the record check: ACQ-A20, A22, A23, A26, A28 and A29. Those six, and the
ownership of each rule by one lens, belong to the rule-ownership spec,
`docs/specs/2026-10-04-criteria-attack-rule-ownership.md`, except ACQ-A23's
clause on template additions, which ACE-D9 decides here. The other
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
- The body of PR 791, the first attack campaign run in this repository,
  records the routing ACE-D6 adopts.
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
differ in one contiguous hunk. A control-only case has no defective document
and no site.

One hunk does not prove one defect, and a planted defect can sit beside an
authored one. So the owner validates a case before its runs count: the case's
lens runs once over the control, and the owner reads every objection it
returns, confirms that the planted defect is the one the parent's Given
clause states (ACE-D3), and that the control carries the parent's no-finding
feature. An objection the owner
upholds, on the case's rule or site or on anything else, means the pair
carries more than its one defect, and the pair is amended. A control-only case is validated by
one panel run, read whole. The validation record under `evals/cases/<id>/`
holds the run's report, the owner's decision and the digests of the validated
documents. The case check refuses a case whose record lacks any of the three
or whose documents differ from the digests.

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
| C8 | ACQ-A8; the what-if question "What if something it relies on is missing?" | `what-if-questions` | what-if | ACE-A32 |
| C9 | ACQ-A9, no verification contract | `verification-contract` | behavioural-outcome | ACE-A33 |
| C10 | ACQ-A10 | `restraint` | obligation-reduction | ACE-A34 |
| C11 | ACQ-A14 | `verified-premise` | set-consistency | ACE-A35 |
| C12 | ACQ-A15, an unspecified window | `stochastic-and-window` | behavioural-outcome | ACE-A36 |
| C13 | ACQ-A16 | `one-obligation` | behavioural-outcome | ACE-A37 |
| C14 | ACQ-A17, advisory findings only | `pending-until-performed` | behavioural-outcome | ACE-A38 |
| C15 | ACQ-A31, a human check on a mechanically checkable property | `verification-contract` | behavioural-outcome | ACE-A45 |
| C16 | ACQ-A18; research answer | `document-deliverable` | behavioural-outcome | ACE-A39 |
| C17 | ACQ-A19 | `has-basis` | obligation-reduction | ACE-A40 |
| C18 | the what-if question "What if it fails?" | `what-if-questions` | what-if | ACE-A42 |
| C19 to C21 | the what-if questions "What if the input is empty or at a limit?", "What if it runs twice, or at the same time?", "What if it runs again with nothing changed?", one case each | `what-if-questions` | what-if | ACE-A57 to ACE-A59 |
| C22 | decision document | `document-deliverable` | behavioural-outcome | ACE-A60 |
| C23 | parent closed before its verification evidence | `one-obligation` | behavioural-outcome | ACE-A61 |
| C24 | unsupported implementation prescription | `restraint` | obligation-reduction | ACE-A62 |
| C25 | stochastic threshold chosen after its results | `stochastic-and-window` | behavioural-outcome | ACE-A63 |
| C26 | a plausible implementation passing every criterion while breaking an in-scope obligation | `sufficiency` | obligation-reduction | ACE-A64 |
| C27 | human measurement without a protocol | `human-measurement` | behavioural-outcome | ACE-A65 |
| C28 | ACQ-A30, a human observer named alone | `human-judgment` | behavioural-outcome | ACE-A44 |
| C29 | incomplete observation window | `stochastic-and-window` | behavioural-outcome | ACE-A66 |
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
- A control run is empty when the lens reports `empty`, which ACQ-A27, the
  parent's empty-control rate, needs.
- A P1 panel run is four runs, one per lens, since any lens could wrongly
  demand implementation criteria of the document. A run passes when the judge
  rules that none of its objections demands criteria for the implementation
  the document describes. A panel run passes when all four of its runs pass.

A missing report, or one whose every objection is malformed, is repeated at
most twice. A run still without a usable report, or holding an objection owed
a judgment that the judge has not given, leaves its case pending and the
evaluation incomplete. A pending case is never scored as a miss.

**ACE-D5 — A calibrated judge decides what the scorer cannot place.** The
judge is Claude Opus through the native Agent tool, with the prompt
`evals/judge.md`.

For a case it receives the case's rule text, its
detection statement and one objection. For P1 it receives one objection alone.
It never sees the lens, the model or the arm.

A judgment task counts only after calibration. The owner, Scott Hamilton,
labels twenty items for the task, and the judge must agree on eighteen. A
prompt that failed calibration is calibrated again only after revision, on
twenty new items.
The experiments' validity and ground-matching tasks are calibrated the same
way.

The twenty items for a case task include mechanical detections. A mechanical
detection can be false: an objection can cite the right rule at the right site
and describe something else. The owner's labels on those items are the check
on that.

An eighteen-of-twenty agreement bounds the judge's disagreement with one
evaluator on one sample of twenty items. It says nothing about documents
unlike that sample.

The run record names the judge's resolved model ID and the judge prompt's
digest. A calibration record names its labeller, its twenty items, and the
prompt digest and judge model ID it calibrated. Two lock sets compare only under one judge model ID and one
prompt digest.

**ACE-D6 — The evaluated configuration is the production configuration.**

| Lens | Transport | Model | Effort | Reads |
| --- | --- | --- | --- | --- |
| behavioural-outcome, obligation-reduction | Codex CLI | `gpt-6.1-sol` | high | its prompt only, in a fresh context, from an empty directory |
| set-consistency, what-if | OpenRouter | `moonshotai/kimi-k3` | low | its prompt only, in a fresh context, with no tools |

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
  its cases' current locks are empty. Each lens run inside a P1 panel run
  enters its own lens's pool, and is empty when that lens reported `empty`.
  The rate is pooled across the lens's cases, so it is no side and earns no
  retest.

A parent criterion passes only when every case serving it is locked. Requiring
every case to pass inside one attempt would fail, on luck alone, about three
attempts in four for a lens that is right nineteen times in twenty.

No rate is averaged across cases. The scorer also reports each lens's pooled
rates, which decide nothing.

With the retest, a lens detecting half the time passes a side with probability
0.20, and one detecting nine times in ten passes with 0.96. The thresholds sit
on purpose above the one baseline there is: the single control false positive
seen across PR 785's attack rounds.

Locking the whole catalogue from nothing plans 310 lens dispatches: the 29
pair cases at two documents and five runs each make 290, and P1's five panel
runs of four lenses make 20. The 21 pair cases on the Codex lenses and P1's
two Codex lenses put 220 of them on Codex. Retests and ACE-D4's repeats come
on top. The planner refuses a larger plan, an experiment's plan included,
unless the plan names the owner's approval. The
owner confirmed the run counts and thresholds on `agents-config-9k9.453`,
after a pilot in which a Codex run took one to three minutes. Changing a
threshold amends this spec. A plan fixes its thresholds (ACE-D8), and the
scorer scores an attempt under the thresholds its plan fixed.

**ACE-D8 — A lock is tied to what produced it.** The planner writes an
attempt's plan before any dispatch, and a retest's extension of it before the
retest. The plan fixes every dispatch, the configuration, the thresholds and
the cases. Every attempt is committed with
its reports under `evals/runs/<run-id>/`, whatever it shows. That rests on the
operator, since nothing sees a run nobody commits. The planner refuses a new
attempt while a planned attempt has no committed reports.

Each report carries the transport's own response metadata: the model it served
and its response ID. The scorer reads the model from there, never from the
plan, and refuses an attempt whose usable reports do not match its planned
runs one to one, or in which two reports share a response ID. A repeat's
superseded reports stay committed and match nothing.

A lock records its case's fingerprint. The fingerprint is the digests of the
prompts emitted for the case's documents, two for a pair case and one for P1,
with ACE-D6's model and effort. An emitted prompt holds the lens body, the
shared template and the rules the lens enforces, so a change to any of them
changes the fingerprint. P1's fingerprint holds its one document's prompt
from each of the four lenses.

A lock is current while its fingerprint matches the tree. A change voids only
the locks whose fingerprint it alters, and only those cases run again.

A change to the judge prompt, the judge model or the scorer dispatches no
lens. The stored reports are rescored, and a lock stands when its case still
passes.

A fingerprint gets one attempt, plus the retest a side at three of five earns
under ACE-D7. The
planner refuses another attempt on it, whether the case locked or failed, so a
failed case is answered only by changing something, and a locked case is not
re-rolled.

"The evaluation of record" is the set of current locks.

**ACE-D9 — Comparison and the template gate.** An addition to the shared
attack template ships only with a whole-catalogue comparison reporting
`improves` against the template without it.

A change improves on its baseline over the same cases when two things hold.
Every case locked under the baseline is locked under the change. At least two
lenses gain a locked case.

A gain in one lens alone belongs in that lens's own prompt.

ACQ-A23, the parent's rule that the shared template changes only on
evaluation evidence, admits an addition that carries this spec's evaluation
evidence. A registry under `evals/` is a chain of template digests. Its first entry is the
template's digest at the commit S2.4 lands, held as a constant in the emitter
suite. Each later entry names the two committed lock
sets its comparison read and the report it produced against the entry before
it. A test pins the current template's digest to the chain's last entry.

## Acceptance criteria

"Passes" means passing under ACE-D4 and ACE-D7. A case passes in the
evaluation of record when it holds a current lock (ACE-D8). The emitter and
checker suites run under `make content-tests`.

- **ACE-A11** The case check refuses a catalogue with no case for a rule the
  standard holds, naming the rule.
- **ACE-A12** The case check refuses a catalogue missing a case ACE-D3 lists,
  or holding a case whose served parents, rule, lens or child differ from
  ACE-D3's table, naming the case.
- **ACE-A13** The case check refuses a case missing a manifest field; a pair
  case whose documents are missing, identical, differ in more than one
  contiguous hunk, or differ from the digests its validation recorded, or
  whose rule its lens does not enforce; a control-only case holding a
  defective document or a site; and a case whose validation record lacks its
  report, the owner's decision or the digests, or whose decision is not an
  acceptance of the recorded documents. It names the case and the fault.
- **ACE-A14** Given fixture reports and verdicts, the scorer counts a detection
  for an objection citing the case's rule at its site, and for one citing only
  the rule or only the site that the judge matches to the detection statement.
  It counts no other objection, and for a case whose site is `none` it counts
  a detection only on a judge match.
- **ACE-A15** Given fixture reports, the scorer passes a case's detection at
  four or five detecting runs of five and, after a retest, at eight to ten of
  ten, and fails it at every other count.
- **ACE-A16** Given fixture reports, the scorer holds a case's control at four
  or five silent runs of five and, after a retest, at eight to ten of ten,
  and fails it at every other count.
- **ACE-A17** Given fixture reports, the scorer passes a lens on ACQ-A27 at 80
  percent empty control runs, fails it below, and fails a lens with no control
  run behind a current lock.
- **ACE-A18** The scorer refuses a run whose model, read from the transport's
  response, or whose effort, transport, isolation under ACE-D6's Reads column,
  or planned run count differs from ACE-D6 and ACE-D7, naming the difference. Repeats do not count against the
  planned run count.
- **ACE-A19** A planned run with no usable report after two repeats, or with an
  objection owed a judgment the judge has not given, leaves its case pending
  and counts in no rate, and the scorer reports the evaluation incomplete.
- **ACE-A20** The scorer refuses to score a judgment task whose calibration
  record is absent, shows fewer than eighteen agreements in twenty, names a
  judge prompt digest or judge model ID other than the run's, or names a
  labeller other than the owner, naming the reason.
- **ACE-A21** The planner refuses an attempt on a case whose current
  fingerprint already has an attempt, locked, failed or retested, naming the
  case, and
  refuses any attempt while a planned attempt has no committed reports, naming
  the open attempt.
- **ACE-A22** Given two fixture lock sets over the same cases, the comparison
  reports `improves` when every case locked in the first is locked in the
  second and at least two lenses gain a locked case. Otherwise it names the
  regressed case or the missing gain.
- **ACE-A23** The comparison refuses two lock sets that differ in ACE-D6's
  configuration, in judge model ID, in judge prompt digest or in the cases
  they cover, or either of which holds a pending case, naming the reason.
- **ACE-A24** The emitter suite fails when the current template's digest is
  not the registry's last entry, when the first entry is not the suite's
  constant, or when an entry after the first lacks a report saying `improves`
  that the comparison reproduces from the committed lock sets the entry
  names, whose fingerprints carry the entry's digest and the one before it,
  the later set covering every catalogue case.
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
- **ACE-A42** C18 passes in the evaluation of record.
- **ACE-A43** Every lens passes ACQ-A27 in the evaluation of record.
- **ACE-A44** C28 passes in the evaluation of record.
- **ACE-A45** C15 passes in the evaluation of record.
- **ACE-A46** The planner plans a retest for every side at three of five and
  for no other, plans no third repeat of a run, and the scorer judges a
  retested side on all ten of its runs.
- **ACE-A47** Given locks and a tree in which one case's document or one
  lens's emitted prompt has changed, the scorer reports as void exactly the
  locks whose fingerprint changed, naming each.
- **ACE-A48** Given stored reports and a changed judge prompt, judge model or
  scorer, the scorer rescores them with no lens dispatch planned, and keeps a lock only
  when its case still passes.
- **ACE-A49** The scorer's report states each lens's pooled detection and
  silence rates over the runs behind its current locks, and names every case
  not locked with its failing or pending side.
- **ACE-A50** Given fixture control reports and verdicts, the scorer counts a
  control run as not silent only when the judge matches one of its objections,
  citing the case's rule or its site, to the detection statement.
- **ACE-A51** Given fixture P1 reports and verdicts, the scorer passes a panel
  run only when none of its four runs holds an objection the judge rules
  demands implementation criteria.
- **ACE-A52** Given fixture reports over a catalogue with passing and failing
  sides, the scorer locks a case only when its detection passes and its
  control holds, locks P1 at four or five passing panel runs of five or
  eight to ten of ten after a retest and at no other count, passes a parent
  only when every case serving it is locked, scores under the
  thresholds the attempt's plan fixed, and averages no rate across cases.
- **ACE-A53** The scorer refuses an attempt whose usable reports do not match
  the planned runs of the attempt and its retest one to one, or in which a
  report lacks a response ID or two share one, naming the run or the report.
  A repeat's superseded reports match nothing.
- **ACE-A54** The planner refuses a plan of more than 310 dispatches that names
  no owner approval, naming the count.
- **ACE-A55** The judge input the scorer assembles holds the case's rule text,
  its detection statement and one objection, or for P1 one objection alone,
  and nothing else.
- **ACE-A56** The scorer refuses a calibration record that shares an item with
  a failed calibration of an earlier prompt digest, that calibrates a prompt
  digest an earlier record failed, or that holds no mechanical detection for
  a case task, naming the reason.
- **ACE-A57** C19 passes in the evaluation of record.
- **ACE-A58** C20 passes in the evaluation of record.
- **ACE-A59** C21 passes in the evaluation of record.
- **ACE-A60** C22 passes in the evaluation of record.
- **ACE-A61** C23 passes in the evaluation of record.
- **ACE-A62** C24 passes in the evaluation of record.
- **ACE-A63** C25 passes in the evaluation of record.
- **ACE-A64** C26 passes in the evaluation of record.
- **ACE-A65** C27 passes in the evaluation of record.
- **ACE-A66** C29 passes in the evaluation of record.
- **ACE-A67** The case check, the scorer and the comparison, run twice over
  unchanged inputs, answer the same way and write nothing; the planner,
  asked twice for the same attempt, refuses the second time under ACE-A21
  and writes no second plan.

### Traceability

| Parent | Child criteria | Check |
| --- | --- | --- |
| ACQ-A1 to A10, A14 to A19, A21, A30, A31 | ACE-A25 to ACE-A41, ACE-A44, ACE-A45, as the catalogue's Child column maps | The scorer's report on the evaluation of record |
| ACQ-A24, apart from rule ownership | ACE-A11 to ACE-A21, ACE-A42, ACE-A46 to ACE-A56, ACE-A57 to ACE-A67, and the cases ACE-A25 to ACE-A40, ACE-A44 and ACE-A45 score | Case check, scorer suite, scorer report |
| ACQ-A27 | ACE-A17, ACE-A43 | Scorer suite, scorer report |
| The template rule in the parent's S2 slice text | ACE-A22 to ACE-A24 | Scorer suite, emitter suite |

### What-if questions

For ACE-A25 to ACE-A45 and ACE-A57 to ACE-A66:

- A failure names the failing case.
- A missing report or verdict leaves the case pending (ACE-A19).
- An attempt beyond a fingerprint's attempt and retest is refused (ACE-A21).
- The empty question does not apply to a fixed document pair.

For ACE-A11 to ACE-A13:

- An empty catalogue fails ACE-A11. A lens with no locks fails ACE-A17.

For ACE-A14 to ACE-A20, ACE-A50 to ACE-A56, and ACE-A67:

- Fixture reports are fixed, so empty does not apply.
- A missing input is ACE-A19. A report the plan does not name is ACE-A53.

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
  ACE-A56, ACE-A67; ACE-D4 to ACE-D8). `evals/plan_run.py`, `evals/score.py` and `evals/judge.md`, their
  suites, and the detection and P1 calibration records. Depends on S2.2.
- **S2.4: Comparison and the template gate** (ACE-A22 to ACE-A24; ACE-D9). A
  comparison mode in `evals/score.py` and the registry test. Depends on S2.3.
- **S2.5: The catalogue** (ACE-D3). The documents in `evals/cases/`, each
  validated under ACE-D2. Cases
  harvested on `agents-config-9k9.441` join in ACE-D2's format when they
  land, and this slice does not wait for them. Depends on S2.2.
- **S2.6: Lens mandates** (ACE-D9; ARO-D1). A baseline attempt on every case, then body
  revisions for the rules the rule-ownership spec newly assigns each lens
  (ARO-D1), each shown by a lens-level
  comparison to regress no case. Depends on S2.3, S2.4 and S2.5.
- **S2.7: Evaluation of record** (ACE-A25 to ACE-A45, ACE-A57 to ACE-A66;
  ACE-D7). The
  verification child for every review-outcome criterion, as ACQ-D2 requires.
  It stays open until every case holds a current lock. Depends on S2.6.

The arm-experiments spec runs its experiments with S2.3's scorer and judge.
They are not S2 slices.

## Continuations

- feat: AC evaluation S2.2: the case check (ACE-D2) — AC: ACE-A11, ACE-A12, ACE-A13; make content-tests exits 0.
- feat: AC evaluation S2.3: planning, scoring and the judge (ACE-D4 to ACE-D8) — AC: ACE-A14, ACE-A15, ACE-A16, ACE-A17, ACE-A18, ACE-A19, ACE-A20, ACE-A21, ACE-A46, ACE-A47, ACE-A48, ACE-A49, ACE-A50, ACE-A51, ACE-A52, ACE-A53, ACE-A54, ACE-A55, ACE-A56, ACE-A67; make content-tests exits 0.
- feat: AC evaluation S2.4: comparison and the template gate (ACE-D9) — AC: ACE-A22, ACE-A23, ACE-A24; make content-tests exits 0.
- feat: AC evaluation S2.5: the catalogue (ACE-D3) — AC: the committed catalogue passes the case check; make content-tests exits 0.
- feat: AC evaluation S2.6: lens mandates (ACE-D9) — AC: a committed baseline attempt on every case, and a lens-level comparison per revised lens that names no regressed case.
- feat: AC evaluation S2.7: evaluation of record, the verification child (ACE-D7) — AC: ACE-A25, ACE-A26, ACE-A27, ACE-A28, ACE-A29, ACE-A30, ACE-A31, ACE-A32, ACE-A33, ACE-A34, ACE-A35, ACE-A36, ACE-A37, ACE-A38, ACE-A39, ACE-A40, ACE-A41, ACE-A42, ACE-A43, ACE-A44, ACE-A45, ACE-A57, ACE-A58, ACE-A59, ACE-A60, ACE-A61, ACE-A62, ACE-A63, ACE-A64, ACE-A65, ACE-A66.

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
