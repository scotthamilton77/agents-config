---
name: test-review
description: Judge whether a test suite would actually fail if the behaviour it covers broke. Use when reviewing test code in a change or pull request, auditing test quality across a package or codebase, investigating flaky or brittle tests, or when a test failure looks caused by the test's design rather than by a bug in the code under test.
admission:
  provides: A test-adequacy lens — the criteria that separate a test which would fail if the required behaviour broke from one that passes regardless, plus the smells whose remedy is the production code rather than the test. Produces findings ranked by severity, each naming the file, the line, and the concrete fix.
  cost: One model-invoked catalog line; a body paid only when a review invokes it, plus a quality reference it hosts for itself and one other skill, paid only when followed.
  remove_when: A mechanical check decides test adequacy — mutation testing gating the same claim — so the judgement no longer needs a reviewer.
---

<!--
Source: skills/test-driven-development/testing-anti-patterns.md
Upstream: https://github.com/obra/superpowers @ f2cbfbefebbfef77321e4c9abc9e949826bea9d7 (v5.1.0)
Last sync: 2026-08-07
Drift policy: selective-amalgamation. Authored here; the mock and test-double
anti-pattern catalog (asserting on a double's existence, test-only methods on
production classes, partial mocks, mocking a side effect the test depends on)
is lifted from the upstream file above and restated as review criteria rather
than as authoring gates. It does not resync byte-for-byte.
-->

# Test review

**Tests are production code for your safety net.** Review them with the rigour
you would give the code they protect. A bad test is worse than no test: it
reports confidence it has not earned, and it will be believed.

The question every finding answers: **would this test fail if the behaviour it
covers broke?** If not, the test is decoration, whatever its coverage number
says.

## Not this skill

- Writing tests from scratch, or making a failing scaffold green — that is the
  `tdd` loop.
- A test failing because the code under test has a bug. That is a diagnosis
  job; come back here once the cause is known and the question is whether the
  test was the right test.
- Throwaway spikes and prototypes. They are meant to be deleted.

## Scope, then context

| Reviewing | Take |
|---|---|
| Named test files | Those files |
| A change or pull request | The test files in the diff |
| A package or directory | Every test file under it |
| A whole codebase | The diff against the trunk first, then widen |

For a codebase-wide audit, order the work: recently changed tests, then tests
covering critical paths, then the rest.

**Read the production code the tests target before judging them.** You cannot
tell whether an assertion pins the right thing without knowing what the right
thing is. A review that only reads the test file grades style.

`references/test-quality.md` holds the depth this checklist compresses — the
tautology filter, the refusal criteria, the double hierarchy, and skip hygiene.
Open it when a finding needs to say *why* rather than just *what*, and whenever
you are judging a test double or a skip.

## Checklist

### Assertions and behaviour

- [ ] Every assertion targets observable behaviour — a return value, a state
      change, a visible side effect — not an internal call
- [ ] No assertion on the mere existence of a test double
- [ ] Test names describe the behaviour verified, not the method invoked
- [ ] The test would survive an internal refactor that preserves behaviour
- [ ] Expected values come from an independent source — a known literal, a
      worked example, the spec — never recomputed the way the code computes them
- [ ] Error paths and boundaries are covered, not only the happy path
- [ ] Each test has one clear reason to fail

### Doubles

- [ ] Fakes preferred to stubs, stubs to spies, spies to mocks
- [ ] Every mock carries a one-sentence justification for existing
- [ ] A double's data mirrors the complete real schema — a partial double
      hides the field downstream code will reach for
- [ ] Nothing the unit under test owns is doubled
- [ ] Doubled side effects are understood; nothing is doubled "to be safe"
- [ ] Five or more doubles in one test — the finding is against the production
      code, not the test

### Isolation and structure

- [ ] Each test sets up its own state and depends on no execution order
- [ ] No shared mutable state across tests
- [ ] Cleanup is complete and not duplicated
- [ ] Deterministic — no wall-clock time, no unseeded randomness, no network
- [ ] Setup and teardown blocks are minimal

### Coverage and hygiene

- [ ] Business logic and validation rules are tested; logging and metrics are not
- [ ] Boundaries exercised: empty, null, maximum, off-by-one
- [ ] Error cases assert the right error, not merely that nothing threw
- [ ] Integration points use real implementations where that is feasible
- [ ] Every skipped test has a reason, a tracking reference, and a re-enable
      condition
- [ ] No commented-out tests
- [ ] No near-duplicate blocks varying one parameter — parameterise them

### Readability

- [ ] Setup is roughly ten lines or fewer per test
- [ ] The intent is clear within five seconds of reading
- [ ] Arrange-act-assert is evident
- [ ] Helpers are named for what they set up

## When the finding is against the production code

These say the design is the problem. Reporting them as test defects sends the
author to fix the wrong file.

- Five or more dependencies need test doubles to reach the code
- Setup exceeds twenty lines of configuration
- The function under test has ten or more conditionals or early returns
- Behaviour can only be verified by asserting on internal calls
- Several tests need the same elaborate setup — a fixture or factory is missing
- A method on a production class is called only from tests

Say so explicitly: better production design is what makes these tests simple,
and no amount of test rewriting substitutes for it.

## Reporting

Rank by severity and give every finding a file-and-line reference, the issue,
and a concrete fix.

- **CRITICAL** — tests that report false confidence: they pass while the code
  is broken, or they assert on a double rather than on behaviour
- **HIGH** — anti-patterns that will cost maintenance: brittle doubles,
  implementation coupling, missing error and boundary cases
- **SUGGESTION** — readability and structure
- **POSITIVE** — tests worth naming as the pattern others should follow

## Smell table

| Smell | Signal | Fix |
|---|---|---|
| Asserting on a double | The assertion checks a double is present | Drop the double, or assert on real behaviour |
| Implementation testing | A "was called with" assertion is the main one | Assert on output or state |
| Tautology | Expected value restates the implementation | Independent literal, worked example, or delete |
| Test-only production method | The method has no caller outside tests | Move it to test utilities |
| Partial double | Response object omits fields real callers read | Mirror the complete schema |
| Too many doubles | Five or more doubles; setup outweighs the test | Refactor the production code |
| Shared mutable state | Tests fail in isolation or in a different order | Fresh state per test |
| Mystery skip | A skip with no reason or tracking reference | Document it or delete it |
| Copy-paste tests | Near-identical blocks, one parameter apart | Parameterise |
| Incidental testing | Assertions on log calls or metric emissions | Delete; test the business rule |
| Flaky timing | A sleep or fixed timeout inside the test | Wait on a condition |
