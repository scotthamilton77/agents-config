# Criteria-attack arm experiments

**Date:** 2026-10-01
**Status:** Draft. Not yet attacked.
**Work item:** `agents-config-9k9.441`, and `agents-config-9k9.442` for the re-attack experiment.
**Scoring contract:** `docs/specs/2026-09-29-acceptance-criteria-evaluation-contract.md`, whose scorer, judge and configuration these experiments run under.

## Problem statement

Two experiments compare ways of running the criteria attack.

- The authoring experiment decides whether one authoring process introduces
  fewer defects than another.
- The re-attack experiment measures what each way of showing a round its
  earlier rejections does to repeats, recall and overturnability.

Neither experiment decides whether a lens meets its parent criteria. That is
the evaluation of record's job. The experiments' results are therefore scored
apart from it, and they change no case's pass or fail.

## Decisions

**ARM-D1 — The authoring-process experiment.** This scores the three arms on
`agents-config-9k9.441`: the orchestrator, the orchestrator with a self-check,
and a subagent with a self-check.

Each arm gets one document at a pinned revision and one fixed set of accepted
objections with the author's decisions. Each authors three times with one
model named in the run plan. The full panel attacks each result once in the
evaluation contract's ACE-D6 configuration.

An introduced defect is either of two things:

- an objection targeting a criterion the arm added or changed that the judge
  rules valid;
- an accepted objection the result leaves unanswered.

An arm ranks ahead when its three results carry at least three fewer
introduced defects in total. A smaller difference is no difference.

**ARM-D2 — The re-attack experiment is judged, not decided.** This scores the
arms on `agents-config-9k9.441` for `agents-config-9k9.442`. The arms are:

1. the document only;
2. the document with a ledger of earlier rejected grounds and their
   rationales;
3. the document only, with a post-filter matching new objections to earlier
   rejections before adjudication.

Fixtures are re-attack rounds from PR 791's history, with seeded wrong
rejections. A seeded wrong rejection is a valid ground the ledger marks
rejected. Each arm runs the full panel five times per fixture in the
evaluation contract's ACE-D6 configuration. Per run, the scorer counts:

- repeats: objections reaching adjudication that the judge matches to an
  earlier rejected ground;
- recall: the share of new valid objections reaching adjudication, where a
  new valid objection is one a later round accepted and no earlier round raised;
- overturnability: whether each seeded wrong rejection reaches adjudication;
- effort: every objection reaching adjudication.

Arm 2 or arm 3 meets the bar when three conditions hold:

- its mean repeats are at most half of arm 1's;
- its mean recall is at most ten percentage points below arm 1's;
- every seeded wrong rejection reaches adjudication in at least four of five
  runs.

The report gives each arm's measures and which arms meet the bar. It selects
no arm and presumes none.

Arm 2 adds text to every prompt, so shipping it would also need the evaluation
contract's ACE-D9 gate.

## Acceptance criteria

- **ARM-A1** Given fixture results with judged introduced defects, the
  authoring report ranks one arm ahead of another only when the first arm's
  three results carry at least three fewer introduced defects in total, and
  reports a smaller difference as no difference.
- **ARM-A2** Given fixture runs, the re-attack report gives each arm's mean
  repeats, mean recall, overturnability and effort.
- **ARM-A3** Given fixture runs, the re-attack report names arm 2 or arm 3 as
  meeting the bar only when all three of ARM-D2's conditions hold for it.
- **ARM-A4** The re-attack report names no arm as selected, whatever the
  measures show.
- **ARM-A5** Given a fixture in which no later round accepted an objection that
  no earlier round raised, the re-attack report states that the fixture has no
  recall value and leaves it out of every arm's mean recall.

## Out of scope

- What a production re-attack round sees, which `agents-config-9k9.442`
  decides with this report as evidence.
- Shipping any arm.
- The scorer, the judge and their calibration records, which the evaluation
  contract builds.
- Harvesting cases for the catalogue, which join it in the evaluation
  contract's format.
