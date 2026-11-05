# Write the spec: audit-log retention

## Problem

The audit log keeps every event it has ever recorded. Nobody has decided how long an event must be kept, what happens to it afterwards, or how a legal hold stops its deletion. The compliance owner and Legal each hold part of the answer, and no retention job can be built until one document records the whole decision.

## This item

This item delivers a decision spec, `specs/audit-log-retention.md`. A later item builds the retention job the spec describes. The spec answers three questions:

- **Q1** At what age, in days, does an audit event leave live storage?
- **Q2** Where does an event go when it leaves live storage, and at what age, in days, is it finally deleted?
- **Q3** How does a legal hold stop the deletion of the events it covers, and what ends a hold?

## Constraints

- **K1** From the compliance owner: every event stays retrievable until it is 400 days old, an event's age being the time since it was written. Retrievable means that the compliance team, asking at any time up to then, obtains the event's full content within 24 hours of asking.
- **K2** From Legal: an event a legal hold covers is never deleted while the hold is in force, wherever it is stored. A hold covers only events that exist when it is placed.

## Decisions

- **D1 Form.** For each part of each question the spec records one chosen answer, at least one alternative it considered, and why the choice is preferred over that alternative.
- **D2 No open questions.** An inconclusive or deferred answer to any part of Q1 to Q3 is not acceptable, because the later item cannot start without all of them.
- **D3 Criteria for the later item.** The spec states the acceptance criteria the retention job will be built against. Those criteria are attacked by an adversarial review against the team's acceptance-criteria standard before this item closes, so the later item starts from criteria that have survived an attack. The attack reads the spec whole, and checks the job criteria against the spec's answers to Q1 to Q3, and against K1 and K2, as their agreed scope. The standard is revision 3 of the team's acceptance-criteria standard, the revision in force on 2026-10-05, and every mention of the standard below means that revision.
- **D4 Judges.** The judges and the standards in the criteria below were agreed with each judge on 2026-10-05, before writing started.

## Acceptance criteria

Each criterion is judged by the person it names, against the standard it states, on one commit of the spec. Each judgment is recorded in the item's review record with the criterion ID, pass or fail, the reason, the commit judged and the judge's name. An entry missing any of these counts as no judgment, including one found after the item closes. The item closes on the spec's latest commit when every criterion has a recorded pass on that commit and none has a recorded fail on it, and it delivers the spec at that commit. A commit with any recorded fail cannot close the item. Until the item closes it stays open. Anything recorded after it closes that would have stopped it closing reopens it: an edit to the spec, a fail on the closing commit, a pass on it found to count as no judgment, or an attack record on that commit that RET-A4 would fail.

- **RET-A1** For every part of Q1 to Q3, the spec gives exactly one chosen answer, at least one alternative considered, and the reason the choice is preferred over that alternative. The platform lead, Mara Lind, fails it if any part of a question has no answer, more than one answer, or a deferred answer, or if any answer lacks an alternative with a reason.
- **RET-A2** The spec's answers keep every event retrievable, as K1 defines it, until it is 400 days old. The compliance owner, Tomas Ruiz, fails it if he can name an event, and a time before or at its age of 400 days, at which the compliance team asking under the spec's answers would not obtain its full content within 24 hours.
- **RET-A3** The spec's answer to Q3 keeps every event a hold covers from deletion while the hold is in force, including an event that has already left live storage when the hold is placed. Legal's reviewer, Ines Achebe, fails it if she can name a covered event that the spec's answers would let be deleted while its hold is in force.
- **RET-A4** The spec's acceptance criteria for the retention job were attacked against the team's acceptance-criteria standard on the commit judged, and no attack on that commit accepted an objection. Accepting an objection means amending the spec, which makes a new commit to attack and judge. Mara Lind reads every attack record on the commit judged, and fails it if the spec states no acceptance criterion for the retention job, if there is no attack record, if any record lacks the list of every objection its attack raised or the statement that its attack finished, if any record does not show that its attack ran against revision 3 of the standard, if any record names as its attacked document anything other than the whole spec at the commit judged, or if any objection in any of them is not rejected with a reason that addresses the scenario the objection states.
- **RET-A5** The spec's answer to Q3 lets a hold cover only events that exist when it is placed. Legal's reviewer, Ines Achebe, fails it if she can name an event written after a hold is placed that the spec's answers would let that hold cover.

## What-if answers

- **It fails.** A recorded fail sends the spec back for revision. A revision is a new commit, which needs a fresh judgment on every criterion and a fresh attack for RET-A4.
- **Empty or at a limit.** An unanswered part of a question fails RET-A1, and D2 rules out an inconclusive answer. An attack that raises no objection is a valid result, and its record passes RET-A4. An event exactly 400 days old is inside K1, which RET-A2 judges.
- **Something missing.** A named judge who is unavailable, or an attack that cannot run, leaves the criterion without a pass, so the item stays open. Nobody else's judgment discharges it.
- **Twice or at once.** Judgments on different commits do not combine, and two judgments of one criterion on one commit close the item only if neither is a fail. Two attacks on one commit are both read by RET-A4.
- **Again with nothing changed.** Judging the same commit again with the same verdict changes nothing.

## Out of scope

- Building, testing or rolling out the retention job. The later item does that against the spec's own criteria.
- Removing or moving any event. This item changes no stored data; the retention job the later item builds applies the spec's answers to every event, including those stored today.
- Who may read audit events, and how reads are recorded, which do not change.
