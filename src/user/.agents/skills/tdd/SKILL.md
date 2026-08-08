---
name: tdd
description: The red-to-green loop and the discipline that keeps it honest. Use when implementing a feature or bugfix test-first, when failing tests have been handed over to be made green, when the user says "red-green-refactor" or "test-first", or when about to write production code that no test yet demands.
admission:
  prevents: The two model defaults that make a test suite prove nothing — writing the implementation first and back-filling tests that pass on arrival, and editing a handed-over failing test until it agrees with the code that was written instead of the contract it encodes.
  cost: Context footprint only, bounded by the caps content-lint enforces.
  remove_when: The executor enforces the loop mechanically — refusing work whose tests did not fail before the implementation existed — so the discipline no longer has to be read to be obeyed.
---

<!--
Amalgam of two upstreams, one Source/Upstream pair each. Every key stays at the
start of its own line: the installer recognises a provenance header by matching
`Source:`/`Upstream:` there, so folding these into prose or bullets would stop
this block being stripped and ship repo-internal paths downstream.

  Source: skills/engineering/tdd/
  Upstream: https://github.com/mattpocock/skills @ 84fdeffd12f2ee307994d1eb6feb48173b6e0502

  Source: skills/test-driven-development/
  Upstream: https://github.com/obra/superpowers @ f2cbfbefebbfef77321e4c9abc9e949826bea9d7 (v5.1.0)
Last sync: 2026-08-07
Drift policy: selective-amalgamation. This body lifts patterns from both
upstreams rather than tracking either byte-for-byte, so it never resyncs
wholesale. Three local decisions a resync would silently revert, and must not:

  - The two-seat split. Both upstreams assume one agent writes the test and
    then the code. Here the implementer seat, handed tests it did not write,
    is first-class and is the seat the loop is stated for.
  - The scoping of the one-slice-at-a-time rule. Upstream forbids writing all
    tests before any implementation, unconditionally. Here that rule binds the
    seat that writes the tests and explicitly permits a reviewed scaffold.
  - The seam gate's unattended path. Upstream stops dead at an unconfirmed
    seam; here an absent user is proceeded past on a recorded decision.

The upstream companion files (tests.md, mocking.md, testing-anti-patterns.md)
are not carried here. Their content was consolidated into the shared test
quality reference so that one file, not four, answers a mocking question.
-->

# Test-driven development

Red to green, one behaviour at a time. Which seat you are in decides who writes
RED. Everything after that is the same.

## Find your seat first

**The tests already exist** — a scaffold, a spec's failing tests, a
reproduction someone handed you. You are the implementer, and those tests are
the contract.

- Make them green **without changing the contract.** Do not edit a test, loosen
  an assertion, rename a symbol it references, or change a signature it calls.
- Run them before you write anything and watch them fail. A handed-over test
  that is already green is a defect in the scaffold. Report it; do not
  implement past it.
- A test you believe is *wrong* is an escalation, not an edit. Name the test,
  what it asserts, and what you think the contract should say instead. Then
  wait.
- Take them one at a time. Green the first, run the suite, green the next.

**No tests exist** — you own both halves, and the loop below is yours end to
end.

## The iron law

**No production code without a failing test first** — whoever wrote the test.

Wrote code before a test existed? Delete it and implement fresh from the test.
Not "keep it as reference", not "adapt it while writing the test": you will
adapt it, and that is testing after. The hours already spent are gone either
way; what you are choosing is whether to keep code that no test has ever caught
a bug in.

## The loop

1. **RED** — one test, one behaviour, a name that says what the behaviour is.
2. **Verify RED** — run it. It MUST fail, and fail *because the behaviour is
   missing*, not because of a typo or a missing import. A test that passes on
   arrival is pinning something that already works: fix the test. A test that
   errors is not yet a test: fix the error and re-run until it fails cleanly.
3. **GREEN** — the simplest code that passes it. No speculative parameters, no
   options object, nothing the next test might want.
4. **Verify GREEN** — run it, then run the rest of the suite. All green, output
   clean. If it fails, fix the code, not the test.
5. **REFACTOR** — only from green, and only to remove duplication or improve
   names. No new behaviour. Stay green.

Then the next behaviour.

## One slice at a time — and what that rule is for

Write one test, then its implementation, then the next test. Do not write five
tests and then five implementations.

The reason is the failure, not the ritual. Tests written in bulk against code
that does not exist yet verify *imagined* behaviour: they pin the shape of
things — signatures, data structures — rather than what a caller can observe,
and they go insensitive to the changes that matter, because you committed to
test structure before you understood the implementation.

**This rule binds the seat that writes the tests. It does not forbid a
scaffold.** A scaffold's tests are not imagined behaviour: they were written
against a contract fixed before them, each one cites the criterion it pins, and
someone other than their author reviewed them for exactly that. Those are the
controls this rule stands in for when they are absent — where they are present,
the rule has nothing left to prevent. In the implementer seat, take the given
tests one at a time and leave them alone.

## Seams — where the test goes

A **seam** is the public boundary you observe behaviour through without
reaching inside. Tests live at seams, never against internals.

You cannot test everything, so decide where the effort lands before spending
it:

- **Tests were handed to you** — the seams are already settled; the tests are
  sitting at them. Nothing to agree.
- **You are writing the tests** — write down the seams you intend to test and
  put that list to the user before writing test code. Domain knowledge re-ranks
  it instantly, and it is the cheapest checkpoint in the cycle.
- **The user is away** — proceed on your own list rather than stalling. Record
  which seams you chose, and why, in the commit or change description. A seam
  decision that is written down is reviewable and cheap to reverse; a stalled
  cycle is neither.

When the shape of the interface is itself the question — how deep the module
is, where the seam belongs, what it should expose — the `codebase-design` skill
carries that vocabulary.

## Before you accept a test into the cycle

Ask what coded decision it pins. If the answer is "the literal I just typed",
or the language, or the standard library, it will pass forever and disagree
with nothing. That filter, the refusal criteria for code too coupled to test,
the fake-over-stub-over-spy-over-mock ordering, and skip hygiene are all in
`../test-review/references/test-quality.md`. Read it when you are about to
write a test double, when setup starts outgrowing the test, or when a test you
just wrote could not fail.

## Red flags — stop

- Production code exists that no failing test asked for
- The test passed the first time you ran it
- You cannot say why the test failed
- You are editing a handed-over test to match code you wrote
- "I already tested it by hand"
- "Tests after achieve the same thing" — they answer *what does this do*; a
  test written first answers *what should this do*, which is the question that
  finds the edge case
- "It is too simple to break"
- "Just this once"

Hard to test means hard to use: when the test is painful to write, the design
is what the test is telling you about. Take that finding to the code.
