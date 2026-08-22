# Rubric: implementation task class

You judge one or more implementations of the same pinned brief, blind. Work through the
phases in order. Score each arm completely and independently before comparing any two.

**What the gate proves, and what it does not.** A green gate proves the arm's tests
pass. It does not prove the acceptance criteria are met: the arm wrote its own tests, so
they verify the arm's *interpretation* of each criterion. The gap between the criterion
as stated and the criterion as tested is yours to audit — it is the highest-value thing
in this rubric. Assume nothing about correctness from a green gate.

## Phase 0 — standing (before any scoring)

- **No-contest**: an arm whose diff is empty. Record it; do not score it.
- **Disqualified**: gate exit non-zero, or an out-of-scope breaking change (a renamed or
  removed field in an existing projection). Record the reason; do not score.
- Everything else is scored, however badly it fails — a failed criterion is data, not
  grounds for refusal.

## Phase 1 — AC evidence audit

For every acceptance criterion in the brief, by ID (if the brief's criteria carry no
explicit IDs, number them in order of appearance — AC1, AC2, … — and use those IDs
consistently), first classify it:

- **Test-expressible** — the criterion names a behavior a test can pin. For these:
  1. Derive the criterion's claim-space from the code yourself — the routes, states,
     and exits over which the claimed behavior must hold. **The arm's tests, comments,
     and docstrings are advocacy, not evidence: never adopt the arm's enumeration of
     the claim-space as your own.**
  2. Locate the test(s) claiming to pin the criterion.
  3. Verdict: **pinned** (tests cover the claim-space and would fail if the behavior
     broke), **partially-pinned** (name the uncovered routes), or **unpinned**.
  4. Where coverage is absent, trace the implementation on the uncovered routes
     yourself and report what you find, with quoted code.
- **Justification-class** — the criterion demands reasoning, reporting, or evidence no
  test can express. Verdict: **met** or **unmet**, judged on the report, no partials,
  with a quoted citation.

Do not average this audit into the axes; it stands on its own.

## Phase 2 — quality axes (0–5 integers, each arm independently)

Bands, all axes: 0 absent · 1–2 deficient (gaps a reviewer must fix) · 3 adequate
(shippable, unremarkable) · 4 strong (a reviewer learns something) · 5 exemplary (the
reference you would show others).

1. **Correctness robustness** — scored from your own Phase 1 derivation, not from
   impression: behavior on routes beyond the criteria's named minimum, boundary states,
   interleavings, refold discipline. A defect you found on an uncovered route caps this
   axis at 2 for that arm.
2. **Test quality** — within the brief's prescription: case selection judgment, pin
   strength (would the suite fail if the behavior broke?), red-first rigor, tests that
   read as behavior pins rather than implementation mirrors.
3. **Decision quality** — the mandated trade-off defense: alternatives genuinely
   weighed, costs acknowledged rather than hidden, and **every factual claim in the
   defense verified by you against the code before it is credited — a claim you did not
   verify with a quote is not evidence, however plausible.**
4. **Fit and scope** — surgical diff, package conventions respected, projection-shape
   impact handled deliberately, nothing touched the task does not require, nothing
   absent the criteria imply.
5. **Engineering quality** — the internal design of what was written, proportionate to
   the diff's size: separation of concerns where the change is large enough for it to
   mean anything; simplicity — the mechanical LOC and cyclomatic complexity
   measurements are evidence, but minimal-at-any-cost is a defect, not a virtue; reuse
   of the package's existing helpers and idioms over private reinvention; dependency
   judgment against the package's existing posture.

Boundary between axes 4 and 5: axis 4 is what the change touches; axis 5 is how well
the touched code is built.

Investigation-fidelity checking is not a seat axis: a separate quarantined checker seat
applies the task's trap ledger. You will not see that ledger; do not try to reconstruct
it.

## Phase 3 — ranking

State which single arm you would ship, citing your Phase 1 audit. With two arms this is
the pairwise preference; with more, name the winner and give a one-line ordering of the
rest. A tie is allowed only when the tied arms are equivalent on the audit and every
axis — explain the equivalence.

## Aggregation (harness-applied, not yours)

Preference majority across seats is the headline result; per-axis means are diagnostic.
A preference tie breaks on total axis mean; a remaining tie is reported as a tie. After
judging, a reconciliation stage verifies the panel's factual findings against the code
and applies each one to every arm uniformly; if the majority preference is contradicted
by that verified ledger, the run is **flagged for human review** — the flag never
silently flips the result, and ledger findings never mutate seat scores.

Validation record for this rubric: `rubric-implementation-validation.md`.
