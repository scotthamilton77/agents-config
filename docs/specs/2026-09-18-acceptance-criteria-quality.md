# Acceptance-criterion and criterion-set quality

**Date:** 2026-09-18
**Status:** Draft for review. No attack or review is claimed for this document.
**Work item:** `agents-config-9k9.424` (the quality-spec split).
**Charter:** `docs/specs/2026-07-21-harness-rework-way-forward.md`, decisions
D1, D3, D4 and D8.

## Problem statement

An agent can satisfy every stated criterion and still deliver the wrong
result. Important outcomes may be missing, the expected behavior may admit
several interpretations, or two criteria may require incompatible results.
Checks of implementation artifacts can also pass without establishing the
behavior the work promises.

Excess detail creates a related failure. A criterion combining independently
deliverable obligations cannot give one slice a useful completion condition.
An implementation prescription adds review surface without necessarily
distinguishing a correct result from an incorrect one.

## Solution and scope

Define one standard for individual criteria and for the set that constitutes
a work item's contract. A set is ready when it covers the material outcomes
and preservation requirements of the agreed scope, has a consistent
interpretation, and leaves no significant product decision unresolved. Every
blocking criterion has a feasible mechanical check with an explicit pass/fail
rule. Implementation choices remain open unless a required outcome or
constraint depends on them.

This document owns the meaning of a sufficient contract, including what
observation establishes success. The AC lifecycle companion owns storage,
references, review timing, amendment, and evidence freshness. Coverage of
promised outcomes belongs here; maintaining the IDs that express that coverage
belongs to lifecycle.

## User stories

1. As an author, I want to expose unresolved product decisions before an
   implementer has to invent answers.
2. As an implementer, I want each assigned criterion to state an assessable
   obligation and leave ordinary implementation choices to me.
3. As a reviewer, I want to identify an in-scope incorrect result that the
   criteria permit, with enough detail to turn it into a check.
4. As a maintainer, I want preservation guarantees to remain binding when
   a change refactors behavior that already works.

## Quality decisions

### ACQ-D1: An observable obligation and its evidence are distinct

A criterion states a required outcome or constraint at an observable surface.
It identifies the relevant starting conditions, action or state, and expected
result. The observer may be a person or a downstream system. Naming an
observer does not require ceremonial wording when the interface makes it
clear.

The proposed check states how to observe that result and decide pass or fail.
Test existence, a green suite, or a changed prompt does not establish a
promised behavior by itself. An artifact property is a valid obligation when
that property is part of the required deliverable or interface. For example,
a consumer's required output format is a contract. Merely adding a sentence
instructing an agent to behave differently is insufficient evidence that its
behavior changed.

Each obligation has a reason in the agreed scope. There is no separate
artifact-to-behavior reference hierarchy or minimum count of criteria in a
particular class.

### ACQ-D2: Granularity follows the obligation

Each criterion states one independently assessable obligation. Split
obligations that can be accepted, rejected, or delivered independently. Keep
together the conditions, cases, and observations needed to establish that
obligation.

For example, "a refused claim leaves the item unchanged" may need assertions
about status, ownership, and notes. Those observations establish one
preservation guarantee. A criterion combining claim eligibility, delivery
eligibility, and installation behavior spans independent obligations and
must be split. The number of test functions or assertions does not decide
granularity.

A slice receives whole criteria it can discharge. A parent outcome may span
slices, but then it remains a parent criterion with separately identified
child obligations. A slice cannot report a parent criterion complete after
implementing only its portion.

### ACQ-D3: Falsifiability includes preservation

A criterion is falsifiable when a violating implementation can make its check
fail. A change criterion normally starts red. A preservation criterion may
already pass and must remain true after the change. A refactor does not need
an invented behavior change to justify keeping its existing guarantees.

Verify factual premises against available code, documentation, or observations
before using them to define the expected result. If a premise is unknown and
changes what success means, the set is not ready. The author identifies the
missing fact or decision rather than presenting an assumption as established.

The existing glossary and authoring instructions say every criterion is
"false today." Adoption replaces that wording with this distinction. The
charter's requirement that criteria be convertible to failing tests remains.

### ACQ-D4: Readiness is a property of the set

The author checks these properties against the agreed scope:

- **Coverage.** Every material promised outcome and required preservation
  guarantee has a criterion. Relevant failure and boundary behavior is
  included. Completeness is bounded by the work's purpose and scope.
- **Consistency.** All criteria can hold together for the same circumstances.
  An individually possible criterion can still contradict another.
- **Decision closure.** A significant ambiguity identifies the decision it
  blocks and the materially different outcomes it permits. An internal design
  choice that preserves the contract does not make the set unready. Verifiable
  facts are investigated; in-scope choices with a clear best answer are made
  under the shared decision rules.
- **Sufficiency.** A plausible implementation that satisfies every criterion
  while violating an in-scope obligation exposes a hole in the set.
- **Restraint.** Each added obligation excludes a concrete in-scope failure or
  pins an explicit constraint. Duplicate obligations and unsupported
  implementation prescriptions do not earn additional criteria.

Apply the charter's taxonomy per criterion: inverse, empty or boundary input,
dependency failure, repeated or concurrent invocation, and idempotency. Record
the relevant case or a reason the dimension does not apply. Several dimensions
may share a case; walking the taxonomy does not require a new criterion for
every cell.

### ACQ-D5: Blocking evidence has a mechanical decision rule

Before implementation, identify a feasible check at the highest relevant
public interface. State its setup, observation, and expected result. The check
must be capable of distinguishing the promised outcome from a plausible
failure. Its eventual passing result is evidence for the criterion.

For a stochastic agent behavior, specify the scenario set, controlled inputs,
run count, and acceptance threshold before evaluating the change. A successful
example alone does not establish reliability outside that observation.

Human judgment can identify important quality concerns, but an attributed
observation alone does not discharge a blocking criterion. Non-mechanical
judgment remains advisory under charter D4 and D8. If a desired outcome cannot
yet be checked mechanically, resolve its verification approach before calling
it a blocking implementation contract. Do not silently substitute an artifact
check for the outcome.

### ACQ-D6: One standard feeds the existing authoring and review paths

The shared acceptance-criteria standard is the deployed home of these quality
rules, subject to the admission gate. Its admission replaces the definition
and taxonomy copies in the authoring skills. The grilling, docs-attached
grilling, spec synthesis, ticketing, briefing, attack, and review-panel skills
cite it at their criteria step. The glossary points to the same standard.

Use the existing attack process. Its criteria-holes, absent-requirements, and
edge-cases mandates retain their work. The proposed behavioral-outcome lens
addresses criterion formulation, granularity, and checkability before those
lenses judge the set. The attack must assess consistency and material
ambiguity across the set as well as individual criteria. This does not create
a second panel or make the tracker classify criterion quality.

Each finding supplies a concrete failing scenario and a proposed criterion or
replacement. Duplicate findings can be rejected against existing coverage.
Every proposal receives a disposition under the existing round contract.
Mechanical validation can check the record and references; it cannot prove
that a model found every semantic defect.

The broader spec-quality work, `agents-config-9k9.226`, retains document
organization and its other requirements. The behavioral-outcome work,
`agents-config-9k9.397`, consumes this standard. Neither needs a private copy.

## Testing decisions

Use the existing skill evaluations and attack prompt/report boundary. Pair
each deliberately defective example with a corrected control. Fix each
example's expected finding, or absence of that finding, before running it.
Run each labelled case three times through the configured attack routes. All
three reports must propose a correction against the expected criterion IDs;
corrected controls must produce no proposals against those criteria. Missing
reports and malformed proposals fail the evaluation. The expected IDs and
required proposal fields are checked mechanically. Explanatory quality remains
advisory. Record the model configuration with the results. This bounded sample
tests detection on known cases and makes no universal claim of reliability.

Briefing checks inspect the generated brief at its consumer boundary. Staging
checks inspect the standard and its citations without deploying to the user's
configuration. The cases below are requirements for those future evaluations;
this documentation change does not claim to have run them.

## Acceptance criteria

- **ACQ-A1** Given a promised behavior supported only by artifact-presence
  checks, the quality review identifies the missing outcome check; a control
  whose required artifact format is itself the delivered interface receives
  no finding merely for describing an artifact.
- **ACQ-A2** Given a criterion with an unspecified condition that changes its
  expected result, the review identifies that missing condition; supplying
  the condition and observable result removes that finding.
- **ACQ-A3** Given two materially different interpretations of required
  behavior, the review names the decision they block; alternative internal
  implementations that satisfy the same contract receive no ambiguity finding.
- **ACQ-A4** Given one criterion combining independently deliverable claim,
  delivery, and installation obligations, the review identifies the required
  split; a single preservation guarantee needing several assertions or
  boundary cases receives no granularity finding for that reason.
- **ACQ-A5** Given a preservation criterion already satisfied before a
  refactor, the review accepts its falsifiability when a violating
  implementation fails its check.
- **ACQ-A6** Given individually satisfiable criteria requiring incompatible
  outcomes for the same input and state, the review identifies the conflicting
  criteria and circumstance; a consistent control receives no conflict finding.
- **ACQ-A7** Given an agreed material outcome absent from the criterion set,
  the review proposes coverage with a failing scenario; an explicitly
  excluded capability receives no missing-requirement finding.
- **ACQ-A8** Given a relevant dependency failure omitted from a criterion's
  taxonomy walk, the review identifies the uncovered outcome; a justified
  inapplicable dimension requires no invented criterion.
- **ACQ-A9** Given a blocking criterion whose evidence has no mechanical
  pass/fail rule, the review identifies the missing verification contract;
  naming a human observer alone does not remove that finding.
- **ACQ-A10** Given a proposed criterion that duplicates existing coverage
  without excluding another in-scope failure, the review identifies the
  existing coverage rather than requiring an additional obligation.
- **ACQ-A11** In staging for every supported tool, the criteria definition and
  taxonomy have one deployed source, and each applicable authoring or review
  skill's criteria step directs its reader to that source.
- **ACQ-A12** Given an assigned criterion set, the generated brief preserves
  exactly those criterion IDs and texts; zero assigned criteria produces a
  refusal instead of an invented contract.
- **ACQ-A13** Given the checks planned for an assigned criterion set, the
  generated brief maps evidence to each criterion separately from its text;
  a criterion without a feasible planned check is reported as unready.
- **ACQ-A14** Given supplied repository evidence contradicting a criterion's
  factual premise, the review identifies the affected criterion and the
  unsupported premise; a control consistent with that evidence receives no
  premise finding.

### Edge-case taxonomy

The paired controls in ACQ-A1 through ACQ-A10 and ACQ-A14 cover the inverse of
each finding. ACQ-A12 covers the empty set; ACQ-A4 covers one obligation with
several observations. Dependency failures are explicit in ACQ-A8 and in the
existing attack rule that a missing lens report leaves a round open.

For every criterion above, repeated evaluation must use the same fixed
scenario and scoring contract. Stochastic reports need not be byte-identical.
Concurrent evaluations use separate round records under the existing attack
contract; this spec adds no shared state. Idempotency applies to adoption:
rerunning staging does not create another standard or change citations.
For review and briefing observations, idempotency of product mutation is
inapplicable because these checks observe generated output and mutate no
product state.

## Ordered slice list

- **S1: Standard adoption** (ACQ-A11). Admit the shared standard, replace
  private definitions with citations, and reconcile the glossary's
  falsifiability wording. This slice changes the normative source.
- **S2: Quality assessment** (ACQ-A1, ACQ-A2, ACQ-A3, ACQ-A4, ACQ-A5, ACQ-A6,
  ACQ-A7, ACQ-A8, ACQ-A9, ACQ-A10, ACQ-A14). Integrate the standard into the existing
  attack mandates and their paired evaluations. This slice depends on S1.
- **S3: Brief fidelity and evidence** (ACQ-A12, ACQ-A13). Align the briefing
  skill and its generated-output evaluations with the standard. This slice
  depends on S1 and can land independently of S2.

## Out of scope

Criteria storage, rendering, attestation, amendment invalidation, and delivery
gates belong to lifecycle. A new spec template, universal defaults for product
requirements, production implementation, and a new review framework are
outside this design. No sentence here grants a model permission to enlarge
the agreed product scope.

## Evidence

The criteria above describe future adoption and evaluation. Their evidence
remains open until that work supplies the named mechanical checks.

- ACQ-A1 | open
- ACQ-A2 | open
- ACQ-A3 | open
- ACQ-A4 | open
- ACQ-A5 | open
- ACQ-A6 | open
- ACQ-A7 | open
- ACQ-A8 | open
- ACQ-A9 | open
- ACQ-A10 | open
- ACQ-A11 | open
- ACQ-A12 | open
- ACQ-A13 | open
- ACQ-A14 | open
