# Rubric: design task class

You judge one or more design documents written to the same pinned brief, blind. The
deliverable is a specification: prose that plans work nobody has done. Work through the
phases in order. Score each arm completely and independently before comparing any two.

**What the gate proves, and what it does not.** The gate is a document linter. A green
gate proves the document has the sections and the criterion syntax the linter demands. It
says nothing about whether a single sentence in it is true, whether the plan would work,
or whether the criteria mean anything. Every judgement of substance in this rubric is
yours to make from the text and from the code the text describes.

**The deliverable makes claims about a tree you can read.** An arm asserting that a module
imports something, that a decision was already taken elsewhere, or that a measurement is
some number, is making a checkable claim. Check the ones the arm's conclusions rest on,
against the repository checkout the harness names, and quote what you find. An unverified
claim is not evidence, however plausible and however confidently stated. This is the
highest-value work in this rubric: a specification's failure mode is not ugliness, it is
being wrong about the thing it plans.

## Phase 0 — standing (before any scoring)

- **No-contest**: an arm whose diff is empty — including an arm that stopped and reported
  rather than delivering. Record it and the reason it gives; do not score it. Stopping on
  a genuine contradiction in the brief is a legitimate outcome and is not a failure.
- **Disqualified**: gate exit non-zero, or the arm changed code, tests or configuration to
  make its document true. Record the reason; do not score.
- Everything else is scored, however badly it fails — a failed criterion is data, not
  grounds for refusal.

## Phase 1 — AC evidence audit

For every acceptance criterion in the brief, by ID (if the brief's criteria carry no
explicit IDs, number them in order of appearance — AC1, AC2, … — and use those IDs
consistently), classify it:

- **Mechanical** — the criterion names something an observer checks by looking: a file at
  a named path, a gate exit, a section present, a list complete. Verdict: **met** or
  **unmet**, with the observation that decides it.
- **Justification-class** — the criterion demands reasoning, evidence or a resolved
  question. Verdict: **met** or **unmet**, no partials, with a quoted citation from the
  document or the arm's report. A criterion the document addresses but gets *wrong* is
  unmet: say so, and say what the truth is.

Two failure modes recur in this class and both read as met if you are not looking for
them. **Assertion in place of evidence**: a criterion demanding the document evidence
something is unmet when the document merely states it — check that the citation is there
and that it says what the arm claims. **Restatement in place of resolution**: a criterion
demanding a question be settled is unmet when the document lists the options, weighs them,
and stops.

Do not average this audit into the axes; it stands on its own.

## Phase 2 — quality axes (0–5 integers, each arm independently)

Bands, all axes: 0 absent · 1–2 deficient (gaps a reviewer must fix) · 3 adequate
(shippable, unremarkable) · 4 strong (a reviewer learns something) · 5 exemplary (the
reference you would show others).

1. **Factual grounding** — is what the document says about the tree true? Scored from your
   own verification, not from the document's confidence: measurements re-derived,
   inventories checked for completeness against the actual tree, cited decisions read to
   confirm they say what the document claims. A load-bearing claim you find false caps
   this axis at 2 for that arm. An arm that inherited a false premise from the brief's own
   context and never tested it is scored here, not excused: the brief said to verify.
2. **Decomposition quality** — do the slices work as units of delivery? Separately
   mergeable in the order given, each flipping a defined set of criteria, each leaving the
   tree in a state that passes its gate on the day it lands, dependencies between slices
   stated rather than implied. A decomposition that only survives if every slice ships
   together is one slice wearing a costume.
3. **Criteria convertibility** — would the document's own acceptance criteria produce
   tests? Each stated as an observable that could be asserted and would fail today, carried
   by a stable ID, naming the inverse or boundary case where one exists. Criteria that can
   only be judged by reading are permitted where the brief permits them and are a defect
   where they stand in for an observable that was available.
4. **Decision quality** — not whether the document's claims are true, which is axis 1's
   question and already answered: whether a decision was actually taken and actually
   defended. Alternatives staged and rejected with the reason, rather than conclusions
   stated and the rejected option never named; costs acknowledged rather than hidden; what
   is reused named alongside what is refused; questions already settled elsewhere cited and
   conformed to rather than re-litigated. Do not re-verify here what you verified in axis 1
   and do not score the same finding twice — carry the verdict across: a decision resting on
   a claim axis 1 found false is undefended, and score it as such in one sentence.
5. **Fit and scope** — the document the brief asked for: the house pattern followed rather
   than described, the boundary drawn with reasons, nothing planned that the task does not
   require, nothing absent that the criteria imply. Length is not evidence in either
   direction — a document is not better for being thorough about the wrong things, nor
   worse for being short about the right ones.

Boundary between axes 2 and 3: axis 2 is whether the pieces are the right pieces; axis 3
is whether each piece states a checkable finish line.

Investigation-fidelity checking is not a seat axis: a separate quarantined checker seat
applies the task's trap ledger. You will not see that ledger; do not try to reconstruct it.

## Phase 3 — ranking

State which single arm's document you would ship, citing your Phase 1 audit. With two arms
this is the pairwise preference; with more, name the winner and give a one-line ordering of
the rest. A tie is allowed only when the tied arms are equivalent on the audit and every
axis — explain the equivalence.

## Aggregation (harness-applied, not yours)

Preference majority across seats is the headline result; per-axis means are diagnostic. A
preference tie breaks on total axis mean; a remaining tie is reported as a tie. After
judging, a reconciliation stage verifies the panel's factual findings against the code and
applies each one to every arm uniformly; if the majority preference is contradicted by that
verified ledger, the run is **flagged for human review** — the flag never silently flips the
result, and ledger findings never mutate seat scores.

Validation record for this rubric: `rubric-design-validation.md`.
