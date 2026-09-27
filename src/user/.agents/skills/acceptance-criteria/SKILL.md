---
name: acceptance-criteria
description: The standard an acceptance criterion and a criterion set must meet. Use when writing, revising, reviewing or attacking acceptance criteria, whether in a spec, a ticket, a plan's exit condition or a dispatch brief, and before claiming work against them.
admission:
  prevents: Criterion sets that pin artifacts instead of the promised behaviour change, such as a sentence being present, a test naming a symbol, or a gate going green. A review campaign then terminates clean on criteria that cannot fail when the behaviour does not change. This happened on a pull request whose four criteria all pinned the artifact; three review rounds converged on them and the change became mergeable with its behaviour unverified.
  cost: Every criteria-attack prompt carries this standard, which enlarges each attacker's input on another vendor's model. Where automation cannot judge an outcome, a set written to this standard names a human evaluator before implementation starts, which puts a round-trip on the human.
  remove_when: Criteria are generated from recorded behavioural observations rather than authored, or attacks judged against this standard stop producing accepted proposals across a run of documents.
---

# Acceptance criteria

A work item's criterion set is its contract. Review judges the work against the set, and the set tells review when to stop. A set that pins the wrong thing lets review finish clean on work that does not do what was promised.

## A criterion

**It states an observable obligation, not the evidence for it.** Name the starting conditions, the action or state, and the result an observer sees. The observer may be a person or a downstream system. The check is separate: it says how to observe that result and decide pass or fail. A test existing, a gate going green, or a sentence added to a prompt does not by itself establish a behaviour. An artifact property is a valid obligation only when the artifact is itself the deliverable or interface, such as the output format a consumer requires.

A research item delivers an evidence-supported answer to a named question. A decision item delivers a reasoned choice against stated constraints. A document existing establishes neither, so say how the answer will be assessed. Say beforehand whether a justified inconclusive result is acceptable.

**It has a basis.** Each obligation traces to the agreed purpose, a decision, a constraint or a preservation guarantee. Reconcile missing coverage against the agreed scope. Growing the scope needs authorization.

**It is one obligation.** Split obligations that can be accepted, rejected or delivered independently. Keep together the cases and observations one obligation needs. "A refused claim leaves the item unchanged" may need assertions on status, owner and notes, and it stays one criterion. The number of tests or assertions does not decide granularity. An outcome spanning slices stays a parent criterion with a named verification child. That child stays open until evidence establishes the parent outcome. Closing the implementation children does not discharge it.

**It can fail.** A criterion is falsifiable when a violating implementation makes its check fail. A change criterion normally starts red. A preservation criterion may already pass and must still hold after the change, so a refactor keeps its guarantees without inventing a behaviour change. Verify a factual premise before using it to define success. An unknown premise that changes what success means leaves the set unready.

## The set

Check the set against the agreed scope before calling it ready:

- **Coverage.** Every material promised outcome and preservation guarantee has a criterion, including relevant failure and boundary behaviour.
- **Consistency.** All criteria can hold together in the same circumstances.
- **Decision closure.** A significant ambiguity names the decision it blocks and the different outcomes it permits. An internal design choice that keeps the contract is not one.
- **Sufficiency.** An implementation that satisfies every criterion while violating an in-scope obligation exposes a hole.
- **Restraint.** Each criterion excludes a concrete in-scope failure or pins an explicit constraint. Duplicates and unsupported implementation prescriptions do not earn a criterion.

Walk the edge-case taxonomy for each criterion. Record the relevant case, or the reason a dimension does not apply. One case may serve several dimensions.

- **Inverse.** The failure path, not only the happy path.
- **Empty or boundary input.** Zero, empty, minimum, maximum, first, last.
- **Dependency failure.** Something the work relies on is absent or errors.
- **Repeated or concurrent invocation.** Run twice, in parallel, interleaved.
- **Idempotency.** A second identical run changes nothing beyond the first.

## Verification

Before implementation, every material commitment has a feasible check at its public interface. The check names its setup, observation, pass/fail rule and required evidence. It names the acceptance authority, which is the rule that decides or the human authorized to judge. It names the completion that waits on the result. It must tell the promise apart from a plausible failure.

Mechanical checks are the default. Human involvement takes two forms:

- **Human-performed measurement** follows a defined protocol judged by a measurable rule. Define the participants, starting conditions, assistance and what counts as done. An agent completing the task does not establish that a human can.
- **Human judgment** needs its assessment standard and its evaluator agreed before implementation. The record names the evaluator's decision, its basis and the revision it covers. Naming a human alone does not make "it feels right" assessable.

A required check stays pending until it is performed. Its cost does not downgrade it, and an advisory review finding cannot discharge it. Resolve an infeasible check, or amend the scope, before calling the set ready.

For stochastic behaviour, fix the scenarios, inputs, run count and threshold before evaluating. For a live observation window, fix the population, collection method, window, missing-data treatment and threshold before collecting. An incomplete window leaves its criterion pending. No result establishes reliability beyond its stated scope.

## Attack before use, and again after amendment

Have a criterion set attacked by adversarial reviewers before work is claimed against it. Attack it again after any amendment to the attacked text, including an amendment a criteria-indicting review forced. An attack on one version says nothing about the next.
