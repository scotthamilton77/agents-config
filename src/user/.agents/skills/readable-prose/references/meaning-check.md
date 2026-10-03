# The meaning check

Run after a revision, before the pass is claimed done. The before-text is the copy kept
outside the working tree; the after-text is the rewrite. Work the document in units: one
decision, one criterion, one stated rule or constraint at a time. For each unit, find its
counterpart in the other text and answer every row below. A row whose answer differs is a
finding, and a finding is reverted or reported. A row whose answer is the same in different
words is recorded as wording only.

## Per unit

| Row | What to compare |
| --- | --- |
| Owner | Who owns the behaviour, the artifact or the decision. A sentence that lost its actor may have moved ownership. |
| Required behaviour | What must happen, under what trigger. |
| Prohibited behaviour | What must not happen. A prohibition folded into a positive sentence is the usual loss. |
| Scope and conditions | The inputs, states, exceptions and preconditions the obligation applies to. A dropped qualifier widens the obligation; an added one narrows it. |
| Named values | Flags, field names, identifiers, exit codes, signals, error text and recorded outputs, byte for byte. |
| Timing and ordering | What happens before what, how long, and what is compatible with what. |
| Cost and removal | The stated cost, the removal or reconsideration condition, and each rejected alternative with its reason. |
| Evidence and status | What was measured versus what is guaranteed, what is uncertain, what is unverified, and the document's own validation status. |

## Per criterion

A criterion is checked on the rows above and on two more:

| Row | What to compare |
| --- | --- |
| Outcome and check | Both the promised outcome and how it is checked are present, and the pass condition is neither weaker nor stronger. |
| Line shape | The identifier and the line form a tool reads are unchanged, and the criterion still sits under the heading that tool reads. |

## The three findings

1. **A narrowed criterion.** The rewrite covers fewer cases, or its check passes on an input the original's refused.
2. **A strengthened claim.** The rewrite asserts more than the original measured or guaranteed. An interpretation that reads better than the measurable condition is the common form.
3. **A resolved conflict.** Two passages in the original disagreed and the rewrite agrees with one of them. The rewrite has chosen a design; the report names the conflict and the rewrite keeps both passages, or keeps the one the owner chose.

## What the report records

- Representative before-and-after pairs: enough to show the rules applied, not every change.
- Which units were checked and how, so a reviewer can repeat the read.
- Each finding and what was done with it: reverted, or reported for the owner.
- Any stale reference repaired, and any conflict left open.
