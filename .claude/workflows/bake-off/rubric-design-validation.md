# Validation — `rubric-design.md`

The standing red test for the design-class rubric, kept out of that file because `bake-off.js` interpolates the rubric wholesale into every judge prompt. A seat told that defects are planted has a reason to find one where none is; these instructions are for whoever maintains the rubric, and no seat scoring an arm should read them.

## Status

Calibrated against a fixture pass and a two-arm contest: the panel reproduced a shipped
document's known verdict, separated two arms by two bands on every axis, and the
quarantined checker caught a blind spot both arms shared and the seat missed.

Condition 1's planted-false-claim step is **discharged**. A copy of the S2 child spec
carried one false load-bearing claim — its audit row enumerated the noun set without
`epic`, which the package's noun enum carried at the tree the audit was performed
against. A single seat scoring Phase 2 and the ship verdict alone returned 2/4/4/4/4
against the clean document's 5/4/5/4/5: it located that claim and no other, quoted the
tree that falsifies it, and invoked the cap rule by name. Fourteen further claims across
every audit row verified true, and axis 4 was left unmoved after the seat checked that no
decision rested on the false claim — the carry-across rule holding as written.

That run also produced this file: the seat named the validation section back and
identified itself as the fixture pass, which is why these instructions no longer travel
in the rubric a judge reads.

## Validation (this rubric's standing red test)

This rubric is untested until all four hold, and any material revision of it re-runs them:

1. **Reference fixture.** The panel scores a document whose quality is independently
   established — a shipped spec of this house's own pattern — and its verdict on that
   document is inspected against what its author and reviewers concluded at the time. A
   fixture is not an arm: it has no diff and no gate run, so the fixture pass runs Phase 2
   and the ship verdict only, and Phases 0 and 1 are skipped rather than improvised. Tell
   the seat which tree to verify against: a shipped document cites the tree as it stood
   when it was written, so a seat handed today's checkout marks true claims unverifiable
   and caps axis 1 for reasons that have nothing to do with the document. Contest arms
   never have this problem — their checkout is the base they wrote against. A
   shipped fixture also tends to pin axis 1 at the ceiling, which measures the fixture and
   not the axis — plant at least one false load-bearing claim in a copy and confirm the
   panel catches it and caps the axis.
2. **Discrimination.** A cheap contest of at least two arms produces a preference the panel
   can defend from Phase 1, not a wash of identical scores.
3. **The checker fires.** The quarantined seat catches the planted probes in the task's
   trap ledger.
4. **Every seat's factual claims carry quoted verification** — a seat that scored axis 1
   without reading the tree has not run this rubric.

Until then, expensive arms are spent on an unmeasured instrument.
