# Acceptance-criterion and criterion-set quality

**Date:** 2026-09-18
**Status:** Draft. Its criteria attack record sits beside it as
`2026-09-18-acceptance-criteria-quality-ac-attack.json`.
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
material commitment has a feasible verification method, an explicit pass/fail
rule, and an acceptance authority. Automate verification where feasible;
identify necessary human participation or judgment before implementation.
Implementation choices remain open unless the contract depends on them.

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

Rule IDs in the standard: `observable-obligation`, `document-deliverable`, `has-basis`.

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

A research spike may deliver an evidence-supported answer to a named question.
A decision item may deliver a reasoned choice against stated constraints.
Document existence or a matching heading does not establish either outcome.
Define how the answer or reasoning will be assessed, including any human
acceptance check. Decide beforehand whether a justified inconclusive result
is acceptable; it is not an automatic substitute for a promised answer.

Each obligation has a basis in the agreed purpose, decisions, constraints, or
preservation guarantees. A parent criterion is one possible basis, not a
mandatory ancestor. Reconcile missing coverage with the agreed scope; obtain
authorization for a scope expansion. No artifact hierarchy or class quota is
required.

### ACQ-D2: Granularity follows the obligation

Rule IDs in the standard: `one-obligation`.

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

A slice receives whole criteria it can discharge. An outcome spanning slices
remains a parent criterion with separately identified child obligations.
Name an explicit verification child in the spec's Continuations manifest
before implementation starts. Its child spec defines the checks and any
dedicated verification slice. That child stays open until evidence establishes
the parent outcome at the relevant interface. It may reuse or combine
sufficient existing checks. A separate integration test is needed only where
those checks leave a gap.
Closing implementation children does not itself discharge the parent. Purely
structural containers need no extra check beyond their children's completion.

### ACQ-D3: Falsifiability includes preservation

Rule IDs in the standard: `can-fail`, `verified-premise`.

A criterion is falsifiable when a violating implementation can make its check
fail. A change criterion normally starts red. A preservation criterion may
already pass and must remain true after the change. A refactor does not need
an invented behavior change to justify keeping its existing guarantees.

Verify factual premises against available code, documentation, or observations
before using them to define the expected result. If a premise is unknown and
changes what success means, the set is not ready. The author identifies the
missing fact or decision rather than presenting an assumption as established.

Existing authoring instructions say every criterion is "false today." Adoption
replaces that wording with this distinction. Automatable change obligations
normally start with a failing test. Preservation guarantees and live
observation windows follow their own verification contracts, even when their
checks are automatable. Human acceptance follows the charter's bounded
exception.

### ACQ-D4: Readiness is a property of the set

Rule IDs in the standard: `coverage`, `consistency`, `decision-closure`, `sufficiency`, `restraint`, `what-if-questions`.

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

Ask the charter's what-if questions of each criterion: what if it fails, what
if the input is empty or at a limit, what if a dependency is missing, what if it
runs twice or concurrently, and what if it runs again with nothing changed.
Record the relevant case or a reason the question does not apply. Several
questions may share a case; answering the questions does not require a new
criterion for every question.

### ACQ-D5: Every commitment has a verification contract

Rule IDs in the standard: `verification-contract`, `human-measurement`, `human-judgment`, `pending-until-performed`, `stochastic-and-window`.

Before implementation, identify a feasible check at the relevant public
interface. State its setup, observation, pass/fail rule, and required evidence.
Name the acceptance authority: the rule that decides a measured result, or the
human authorized to judge it. Name the work item's completion that waits for
the result. The check must distinguish the promise from a plausible failure.

Mechanical verification is the default. Human involvement takes two forms:

- **Human-performed measurement.** A defined protocol produces observations
  judged by a measurable rule. For example, four of five first-time users
  complete a named task within two minutes without help. Define participants,
  starting conditions, assistance, and successful completion. An automated
  agent completing the task does not establish human usability.
- **Human judgment.** Where automation cannot establish the required property,
  agree the assessment standard and designated evaluator before implementation.
  A human acceptance check records that evaluator's actual decision, its basis,
  and the artifact revision or observation it covers. Naming a human alone does
  not make "the interface feels good" assessable. A recorded approval can be
  checked mechanically without making the underlying judgment mechanical.

Every material commitment blocks acceptance at its declared completion boundary.
Advisory findings cannot discharge it. A required human check stays pending
until performed; cost or difficulty does not authorize downgrading it. Resolve
an infeasible check or obtain an explicit scope amendment before calling the
contract ready. Ordinary advisory review findings remain non-blocking under
charter D8; planned human acceptance is the charter's separate, bounded check.

For controlled evaluations of stochastic behavior, specify scenarios, inputs,
run count, and threshold before evaluation. For live observation windows,
specify the population, collection method, window, missing-data treatment, and
threshold before collection. Define a baseline when comparison requires one.
Window evidence can block milestone completion without blocking its individual
PRs. An incomplete window leaves the criterion pending. Neither a successful
example nor a window result establishes reliability beyond its stated scope.

The ledger retains `observed:` for dated, attributed observations, including
human acceptance. Its referenced account must supply the agreed protocol or
assessment, evidence, and result; the row alone proves no outcome. Existing
records keep their meaning. Spec-lint checks ledger structure, not evidence
sufficiency. Adoption reconciles blanket mechanical-only completion wording
with the charter amendment; it does not add a new review-finding class.

### ACQ-D6: One standard feeds the existing authoring and review paths

The shared acceptance-criteria standard is the deployed home of these quality
rules, subject to the admission gate. Each rule there carries the ID its
decision above lists, so a lens, an objection and this spec name a rule the
same way. Its admission replaces the definition
and what-if copies in the authoring skills. The grilling, docs-attached
grilling, spec synthesis, ticketing, briefing, attack, and review-panel skills
cite it at their criteria step. The glossary points to the same standard.

Use the existing attack process, with four lenses. Each lens names the rules
it enforces, and its prompt carries exactly those rules.

- A behavioral-outcome lens addresses criterion formulation, granularity, and
  checkability.
- An obligation-reduction lens inventories the document's obligations and
  maps the criteria onto them. An obligation part no criterion completely
  discharges is a gap, and a criterion that discharges no part lacks a basis.
  The inventory is returned with the report, so the reduction can be audited.
- A set-consistency lens addresses contradiction and material ambiguity
  across the set.
- A what-if lens asks the what-if questions of each criterion.

An objection's ground cites the ID of the rule it concerns, and that rule
must be one its lens enforces. This does not
create a second panel or make the tracker classify criterion quality.

Each finding is an objection. It names the criterion it concerns, or none, the
rule of this standard that the criteria break, and a concrete failing scenario.
An attacker reads the document with less context than its author, so the
author writes any new or replacement criterion an accepted objection needs.
An attacker that drafts criteria substitutes its narrower reading for the
author's. Attacking a spec-authoring item, for example, it demands criteria for
the implementation the spec only describes. Duplicate findings can be rejected
against existing coverage. Every objection receives a disposition under the
existing round contract.
Mechanical validation can check the record and references; it cannot prove
that a model found every semantic defect.

The broader spec-quality work, `agents-config-9k9.226`, retains document
organization and its other requirements. The behavioral-outcome work,
`agents-config-9k9.397`, consumes this standard. Neither needs a private copy.

## Testing decisions

Use the existing skill evaluations and attack prompt/report boundary. Pair
each deliberately defective example with a corrected control. The quality
assessment child spec defines how a result demonstrates detection of the
intended defect; matching its criterion ID and objection shape alone is
insufficient. It assigns cases to the responsible lenses and identifies any
cases requiring the full panel.

Before implementation, that child spec settles the model configuration,
repetition policy, evaluation budget, and pass/fail thresholds from baseline
observations. It identifies any human or model judgment used in scoring and
the limits of that evidence. This parent sets no fixed run count or unanimity
rule. Designing, calibrating, and running those evaluations belongs to the
child work, not to this documentation PR.

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
- **ACQ-A5** Given a preservation check that cannot fail under a violating
  implementation, the review identifies the unfalsifiable check; a criterion
  already satisfied before a refactor is accepted when a violating
  implementation fails its check.
- **ACQ-A6** Given individually satisfiable criteria requiring incompatible
  outcomes for the same input and state, the review identifies the conflicting
  criteria and circumstance; a consistent control receives no conflict finding.
- **ACQ-A7** Given an agreed material outcome absent from the criterion set,
  the review objects that it is uncovered, with a failing scenario; an explicitly
  excluded capability receives no missing-requirement finding.
- **ACQ-A8** Given a relevant dependency failure omitted from a criterion's
  what-if answers, the review identifies the uncovered outcome; a justified
  inapplicable dimension requires no invented criterion.
- **ACQ-A9** Given a commitment without a feasible verification contract,
  the review identifies what is missing; a defined human measurement, or a
  defined judgment check on a property automation cannot establish, is
  accepted, while naming a human observer alone is not.
- **ACQ-A10** Given a criterion that duplicates existing coverage without
  excluding another in-scope failure, the review objects on restraint and
  names the existing coverage; a criterion excluding a distinct in-scope
  failure receives no duplicate finding.
- **ACQ-A11** In staging for every supported tool, the criteria definition and
  what-if questions have one deployed source, and each applicable authoring or review
  skill's criteria step directs its reader to that source, as does the
  glossary. Authoring and completion instructions contain no contradictory private
  quality rule.
- **ACQ-A12** Given an assigned criterion set, the generated brief preserves
  exactly those criterion IDs and texts; zero assigned criteria produces a
  refusal instead of an invented contract. An assigned criterion whose text
  cannot be retrieved, including when its source cannot be read, produces a
  refusal naming that criterion instead of a brief that omits or invents it.
- **ACQ-A13** Given the checks planned for an assigned criterion set, the
  generated brief maps evidence to each criterion separately from its text;
  a criterion without a feasible planned check is reported as unready.
- **ACQ-A14** Given supplied repository evidence contradicting a criterion's
  factual premise, the review identifies the affected criterion and the
  unsupported premise; a control consistent with that evidence receives no
  premise finding.
- **ACQ-A15** Given a window-based criterion, the review accepts a defined
  observation protocol and completion boundary without requiring controlled
  inputs or per-PR gating; an unspecified window receives a finding.
- **ACQ-A16** Given a parent outcome spanning slices, the review identifies
  missing verification ownership; an explicit verification child using
  sufficient existing checks needs no duplicate integration test.
- **ACQ-A17** Given material commitments supported only by advisory findings,
  the review identifies the missing acceptance checks. Given a human judgment
  check assigned to a property that a mechanical check at the public interface
  could establish, the review identifies the feasible mechanical check. A set
  whose human checks each cover a property automation cannot establish receives
  no finding for the number of human checks it uses.
- **ACQ-A18** Given a research deliverable checked only for document existence,
  the review identifies the missing answer assessment; an evidence-supported
  answer, or a justified inconclusive result permitted by the contract,
  receives no finding merely because it delivers knowledge rather than code.
- **ACQ-A19** Given an obligation grounded in an agreed decision or preservation
  guarantee, the review accepts that scope basis without demanding a parent AC;
  a proposed capability outside the agreed scope requires authorization.
- **ACQ-A20** Every attack finding names the criterion it concerns or none,
  the rule of this standard that the criteria break, and a failing scenario;
  the finding carries no drafted criterion. The record refuses a finding whose
  ground cites a rule its lens does not enforce.
- **ACQ-A21** Given a spec-authoring item whose criteria assess the spec's
  content, the review raises no finding demanding criteria for the
  implementation the spec describes.
- **ACQ-A22** The attack runs exactly the four lenses of ACQ-D6, no more and no
  fewer.
- **ACQ-A23** Each lens's prompt consists of that lens's own instructions and
  all four of the shared template's contracts, and nothing else: the fenced
  document, the rules the lens enforces, the output shape, and the explicit
  empty result.
- **ACQ-A24** For every rule ID in the standard, the quality assessment's
  evaluation set holds at least one defective document and a corrected control.
  The review objects to the defective document on that rule, and passes the
  control without that objection. The cases include each of the five what-if
  questions, a decision document as well as a research answer, a parent closed
  before its verification evidence, an unsupported implementation prescription,
  a stochastic evaluation whose threshold is chosen after its results, and an
  incomplete observation window.
- **ACQ-A25** Every rule in the deployed standard carries the ID its decision
  above lists.
- **ACQ-A26** Each lens's prompt carries exactly the standard rules that lens
  names, and a lens naming a rule the standard does not hold is refused before
  any prompt is emitted.
- **ACQ-A27** Given a control document with no defect within a lens's rules,
  that lens returns a valid empty report.
- **ACQ-A28** The record check refuses an obligation-reduction report whose
  inventory is missing or malformed, and one whose undischarged obligation part
  has no objection naming it.

### What-if questions

Every review case in this set shares three answers, so they are stated once
here and not repeated per row. These cases are ACQ-A1 to ACQ-A10, ACQ-A14 to
ACQ-A19, ACQ-A21 and ACQ-A27.

- **Something missing:** a lens that returns no report leaves the round open,
  under the existing attack contract.
- **Twice, or at the same time:** a repeated evaluation reruns the same fixed
  case under the S2 child spec's scoring contract, and concurrent rounds keep
  separate records.
- **Nothing changed:** does not apply, because a review observes output and
  changes nothing.

Each such case is one fixed document, so the empty-or-at-a-limit question
does not apply to it.

| Criterion | What if it fails? | Other questions |
| --- | --- | --- |
| ACQ-A1 | The artifact-format control | Shared answers |
| ACQ-A2 | Supplying the condition removes the finding | Shared answers |
| ACQ-A3 | Alternative internal implementations get no finding | Shared answers |
| ACQ-A4 | One preservation guarantee with several assertions gets no finding | Shared answers |
| ACQ-A5 | A criterion that passes before a refactor, and fails under a violating implementation, is accepted | Shared answers |
| ACQ-A6 | The consistent control | Shared answers |
| ACQ-A7 | An explicitly excluded capability gets no finding | Shared answers |
| ACQ-A8 | A justified inapplicable question needs no criterion | Shared answers |
| ACQ-A9 | Defined human checks are accepted | Shared answers |
| ACQ-A10 | A criterion excluding a distinct failure gets no finding | Shared answers |
| ACQ-A11 | A skill carrying a private copy, or a glossary without the pointer, fails staging | Empty: does not apply. Missing: staging without the standard leaves the citing skills pointing at no source, which fails this criterion's single-source check. Twice and nothing changed: rerunning staging leaves one source, which is the installer's own guarantee. |
| ACQ-A12 | A brief that rewords, drops or invents a criterion fails | Empty: zero criteria refuses. Missing: an unretrievable criterion refuses by name. Twice: each generation is checked separately. Nothing changed: does not apply, because a brief changes nothing. |
| ACQ-A13 | A criterion without a feasible planned check is reported unready | Empty: zero criteria refuses under ACQ-A12. Missing: with no planned checks, every criterion is unready. Twice and nothing changed: as ACQ-A12. |
| ACQ-A14 | The control consistent with the evidence | Shared answers |
| ACQ-A15 | The defined window is accepted | Shared answers |
| ACQ-A16 | A verification child using existing checks needs no duplicate test | Shared answers |
| ACQ-A17 | Human checks on properties automation cannot establish get no finding | Shared answers |
| ACQ-A18 | An assessed answer, or a permitted inconclusive result, gets no finding | Shared answers |
| ACQ-A19 | A capability outside the agreed scope requires authorization | Shared answers |
| ACQ-A20 | The record refuses a finding lacking a ground or scenario, or citing a rule its lens does not enforce | Empty: a lens finding nothing reports empty, under ACQ-A23. Missing, twice, nothing changed: the existing attack contract. |
| ACQ-A21 | A spec whose criteria only check that it exists receives the document-deliverable finding under ACQ-A18's rule | Shared answers |
| ACQ-A22 | A missing lens fails | At a limit: a fifth lens fails. Twice and nothing changed: emission is deterministic. Missing: a missing lens is the failure case. |
| ACQ-A23 | A prompt carrying a passage outside the four contracts fails | Missing: a prompt lacking one of the four contracts fails. Twice and nothing changed: emission is deterministic. Empty: does not apply. |
| ACQ-A24 | A rule with no defective case, or a defective case the review misses, fails | Empty: a rule with only a control fails. Missing: a rule added to the standard without cases fails. Twice: the S2 scoring contract. Nothing changed: does not apply, because evaluation changes nothing. |
| ACQ-A25 | A rule without its ID fails | Empty: does not apply. Missing: a decision listing an ID the standard lacks fails. Twice and nothing changed: staging reads the source unchanged. |
| ACQ-A26 | A prompt carrying another lens's rule fails | Missing: a rule the standard lacks is refused at emission. Twice and nothing changed: emission is deterministic. Empty: a lens naming no rule is refused. |
| ACQ-A27 | A lens objecting to a defect-free control fails | Shared answers |
| ACQ-A28 | A report whose inventory is missing, malformed, or has an undischarged part without an objection is refused | Empty: an inventory with no undischarged part needs no objection. Twice and nothing changed: the check is a read. Missing: a missing inventory is the failure case. |

## Ordered slice list

- **S1: Standard adoption** (ACQ-A11, ACQ-A25). Admit the shared standard, replace
  private definitions with citations, and reconcile authoring and completion
  instructions with preservation and planned human acceptance. The glossary
  points to that standard. This slice changes the deployed normative source.
- **S2: Quality assessment** (ACQ-A1, ACQ-A2, ACQ-A3, ACQ-A4, ACQ-A5, ACQ-A6,
  ACQ-A7, ACQ-A8, ACQ-A9, ACQ-A10, ACQ-A14, ACQ-A15, ACQ-A16, ACQ-A17,
  ACQ-A18, ACQ-A19, ACQ-A20, ACQ-A21, ACQ-A22, ACQ-A23, ACQ-A24, ACQ-A26,
  ACQ-A27, ACQ-A28). First
  settle the assessment and evaluation contract in its child spec. Then
  integrate the standard into the existing attack mandates and their
  evaluations. Each lens owns its prompt, and the
  shared attack template holds only the standard reference, the output shape,
  the explicit empty result, and the fenced document. This evaluation contract
  governs any addition to that shared template: an addition ships only with
  evaluation evidence that it improves the lenses it reaches. Implementation
  depends on S1.
- **S3: Brief fidelity and evidence** (ACQ-A12, ACQ-A13). Align the briefing
  skill and its generated-output evaluations with the standard. This slice
  depends on S1 and can land independently of S2.

## Continuations

These entries name the slice scopes. Before implementation, use `work promote`
on each resulting feature to create its design child and blocked implementation
placeholder. Its child spec carries the implementation manifest and the
dependencies above. Completing a design child does not discharge the parent
criteria; their evidence remains open until implementation supplies it.

- feat: AC quality standard adoption — AC: ACQ-A11, ACQ-A25
- feat: AC quality assessment and evaluation contract — AC: ACQ-A1, ACQ-A2,
  ACQ-A3, ACQ-A4, ACQ-A5, ACQ-A6, ACQ-A7, ACQ-A8, ACQ-A9, ACQ-A10, ACQ-A14,
  ACQ-A15, ACQ-A16, ACQ-A17, ACQ-A18, ACQ-A19, ACQ-A20, ACQ-A21, ACQ-A22,
  ACQ-A23, ACQ-A24, ACQ-A26, ACQ-A27, ACQ-A28
- feat: AC brief fidelity and evidence mapping — AC: ACQ-A12, ACQ-A13

## Out of scope

Criteria storage, rendering, attestation, amendment invalidation, and delivery
gates belong to lifecycle. A new spec template, universal defaults for product
requirements, production implementation, and a new review framework are
outside this design. No sentence here grants a model permission to enlarge
the agreed product scope.

## Evidence

The criteria above describe future adoption and evaluation. Their evidence
remains open until that work supplies the agreed verification results.

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
- ACQ-A15 | open
- ACQ-A16 | open
- ACQ-A17 | open
- ACQ-A18 | open
- ACQ-A19 | open
- ACQ-A20 | open
- ACQ-A21 | open
- ACQ-A22 | open
- ACQ-A23 | open
- ACQ-A24 | open
- ACQ-A25 | open
- ACQ-A26 | open
- ACQ-A27 | open
- ACQ-A28 | open
