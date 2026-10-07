# Criteria-attack arm experiments

**Date:** 2026-10-01
**Status:** Draft. Attacked once, on 2026-10-07; the record is beside this file.
**Work item:** `agents-config-9k9.441`, and `agents-config-9k9.442` for the re-attack experiment.
**Scoring contract:** `docs/specs/2026-09-29-acceptance-criteria-evaluation-contract.md`, whose scorer, judge and configuration these experiments run under.

## Problem statement

Two experiments compare ways of running the criteria attack.

- The authoring experiment decides whether one authoring process introduces
  fewer defects than another.
- The re-attack experiment measures what each way of showing a round its
  earlier rejections does to repeats, recall and overturnability.

Neither experiment decides whether a lens meets its parent criteria. That is
the job of the evaluation of record, the evaluation contract's set of current
locks (ACE-D8). The experiments' results are therefore scored
apart from it, and they change no case's pass or fail.

## Decisions

**ARM-D1 — The authoring-process experiment.** This scores the three arms on
`agents-config-9k9.441`: the orchestrator, the orchestrator with a self-check,
and a subagent with a self-check. The orchestrator authors the criteria in
the context that holds the objections and decisions. A self-check is one
read of the amended criteria against the acceptance-criteria standard's
one-obligation, observable-obligation and consistency rules, with edits,
before the attack; the orchestrator arm does it in the same context, and the
subagent arm authors and self-checks in a fresh context given only the
document, the objections with their decisions, and the standard.

Each arm gets one document at a pinned revision and one fixed set of accepted
objections with the author's decisions. Each authors three times with one
model named in the run plan. The full panel attacks each result once in the
evaluation contract's ACE-D6 configuration.

An introduced defect is either of two things:

- an objection targeting a criterion the arm added or changed that the judge
  rules valid;
- an accepted objection the result leaves unanswered.

An arm ranks ahead when, and only when, its three results carry at least
three fewer introduced defects in total. A smaller difference is no
difference. An arm with fewer than three results ranks nowhere.

**ARM-D2 — The re-attack experiment is judged, not decided.** This scores the
re-attack arms listed on `agents-config-9k9.441`; `agents-config-9k9.442`
consumes the result. The arms are:

1. the document only;
2. the document with a ledger of earlier rejected grounds and their
   rationales;
3. the document only, with a post-filter before adjudication: each new
   objection the judge matches to an earlier rejected ground is held out of
   adjudication and listed to the adjudicator as a repeat, with the ground it
   matched; nothing is dropped. A held-out objection is not adjudicated, so
   it counts in neither repeats nor effort, and the report gives the
   held-out count beside them; it does reach the adjudicator, so a seeded
   wrong rejection listed as a repeat counts as reaching adjudication for
   overturnability.

Fixtures are re-attack rounds from the history of PR 791, the first attack
campaign run in this repository, each with at least one seeded wrong
rejection. A seeded wrong rejection is a ground the judge has
ruled valid and the ledger marks rejected. Each arm runs the full panel five
times per fixture in the evaluation contract's ACE-D6 configuration. Per run,
the scorer counts:

- repeats: objections reaching adjudication that the judge matches to an
  earlier rejected ground;
- recall: the share of new valid objections reaching adjudication, where a
  new valid objection is one a later round accepted and no earlier round raised;
- overturnability: per seeded wrong rejection, whether it reaches the
  adjudicator, adjudicated or listed as a repeat;
- effort: every objection reaching adjudication.

Arm 2 or arm 3 meets the bar when three conditions hold:

- its mean repeats are at most half of arm 1's;
- its mean recall is at most ten percentage points below arm 1's;
- every seeded wrong rejection reaches adjudication in at least four of five
  runs.

The report gives each arm's measures per fixture and as means over the
fixtures that have a value, its overturnability per seeded wrong rejection as
the count of runs in which it reached adjudication, and which arms meet the
bar. When no fixture has a recall value, the report states that the recall
condition cannot be judged, and no arm meets the bar. The report selects no
arm and presumes none.

Arm 2 adds text to every prompt, so shipping it would also need the evaluation
contract's ACE-D9 gate.

**ARM-D3 — An experiment runs under a plan, apart from the evaluation of
record.** The plan is written before dispatch, as the evaluation contract's
ACE-D8 asks of an attempt. It fixes each arm and the process it runs, the
document revision and the objection set, the model, the fixtures with their
seeded wrong rejections and the judge's validity ruling on each, the run
counts, and each arm's prompt as the ac-attack emitter produces it at plan
time, with arm 2's ledger added. A self-check arm's run records the criteria
before and after the self-check. Every run is committed with its plan and
reports under `evals/experiments/<run-id>/`, one run-id per run, and an
experiment writes nowhere else, so the evaluation of record's locks are the
same before and after it.

The scorer, the judge and the lens configuration are the evaluation
contract's (ACE-D5, ACE-D6), and a run recorded under another does not count.
The experiments add three judge tasks, calibrated as ACE-D5 says. The
validity task gives the judge the rule text and one objection and asks
whether the objection holds under the rule. The ground-matching task gives
one objection and one earlier rejected ground with its rationale and asks
whether they are the same ground. The incorporation task gives one accepted
objection with the author's decision and the result's added and changed
criteria, and asks whether the result answers the objection. Each returns
yes or no with a reason, and the judge sees no arm, lens or model. Each task has its own prompt, calibrated and digested on
its own under ACE-D5; the panel's judge prompt digest is the contract's.
A run with no usable report is repeated at most twice, as ACE-D4 says. A
fixture or an authoring result still missing is pending: the report leaves it
out of every measure and names it, an arm with a pending result ranks
nowhere, and an arm with a pending fixture meets no bar.

## Acceptance criteria

The scorer is the evaluation contract's, run over experiment inputs.

- **ARM-A1** Given fixture results with judged introduced defects, the
  authoring report ranks one arm ahead of another exactly when the first arm's
  three results carry at least three fewer introduced defects in total,
  reports a smaller difference as no difference, and ranks an arm with fewer
  than three results nowhere, naming it pending.
- **ARM-A2** Given fixture runs, the re-attack report gives each arm's repeats,
  recall and effort per fixture and as means over the fixtures that have a
  value, its overturnability per seeded wrong rejection as the count of runs
  in which it reached the adjudicator, and for arm 3 the held-out count
  beside repeats and effort.
- **ARM-A3** Given fixture runs, the re-attack report names arm 2 or arm 3 as
  meeting the bar exactly when all three of ARM-D2's conditions hold for it
  and none of its fixtures is pending.
- **ARM-A4** The re-attack report names no arm as selected or as the expected
  default, whatever the measures show.
- **ARM-A5** Given a fixture in which no later round accepted an objection that
  no earlier round raised, the re-attack report states that the fixture has no
  recall value and leaves it out of every arm's mean recall; when no fixture
  has one, it states that the recall condition cannot be judged and names no
  arm as meeting the bar.
- **ARM-A6** The scorer refuses an experiment run whose model, effort,
  transport, isolation, judge model ID or panel judge prompt digest differs
  from the evaluation contract's ACE-D5 and ACE-D6, whose prompt differs from
  the one its plan fixed for its arm, or whose validity, ground-matching or
  incorporation task has no passing calibration record for its prompt
  digest, naming the difference.
- **ARM-A7** The scorer refuses a plan that omits a part ARM-D3 fixes, whose
  run counts or panel membership differ from ARM-D1 and ARM-D2, whose
  objection set holds an objection without the author's decision, whose arm 2
  ledger lacks a rationale for a ground, or whose run-id a committed run
  already holds; and it refuses a run set whose usable reports do not match
  the plan's runs one to one in arm, fixture, document revision, objection
  set, model and arm prompt, whose self-check run lacks the criteria before
  and after the self-check, or whose fixture names no committed attack record
  of PR 791 or lacks a seeded wrong rejection with a validity ruling, naming
  the difference. A repeat's superseded reports match nothing.
- **ARM-A8** The runner's write log for an experiment run names no path
  outside `evals/experiments/<run-id>/`, and the evaluation of record's locks
  are the same before and after it.
- **ARM-A9** Given attack reports, judge verdicts and a result's added and
  changed criteria, the scorer counts as introduced defects exactly the valid
  objections targeting an added or changed criterion and the accepted
  objections the incorporation task rules unanswered, an objection in both
  classes counting once.
- **ARM-A10** Given a fixture run's adjudication record, the scorer's repeats,
  recall, overturnability and effort for that run are the counts ARM-D2
  defines, and the report uses those counts; for arm 3 the record holds the
  held-out objections listed with their matched grounds and none of them
  adjudicated, or the scorer refuses it.
- **ARM-A11** A run with no usable report after two repeats leaves its fixture
  or authoring result pending, and the runner plans no third repeat; the
  report leaves a pending input out of every measure, names it, ranks no arm
  on it, and names no arm as meeting the bar over it.
- **ARM-A12** The input the scorer assembles for the validity task holds the
  rule text and one objection, for the ground-matching task one objection and
  one earlier rejected ground with its rationale, and for the incorporation
  task one accepted objection with its decision and the result's added and
  changed criteria, each stripped of any field naming a lens, arm or model,
  and nothing else; a verdict that is not yes or no with a reason makes the
  run's report unusable under ARM-A11.

## Out of scope

- What a production re-attack round sees, which `agents-config-9k9.442`
  decides with this report as evidence.
- Shipping any arm.
- The scorer, the judge and their calibration records, which the evaluation
  contract builds; the experiments add inputs to the scorer, not a scorer.
- Harvesting cases for the catalogue, which join it in the evaluation
  contract's format.
