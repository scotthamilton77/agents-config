---
name: test-review
model: opus
context: fork
agent: general-purpose
description: Use when doing code review of unit or integration tests, reviewing test quality in a PR, auditing test patterns across a package or codebase, or when test failures seem caused by test design rather than production bugs
---

# Test Review

## Core Principle

**Tests are production code for your safety net.** Review them with the same rigor as the code they protect. A bad test is worse than no test — it provides false confidence.

## When to Use

- Reviewing test code in a PR or commit
- Auditing test quality across a package or codebase
- Investigating flaky or brittle tests
- Reviewing newly written tests (yours or another agent's)
- Post-TDD review to catch patterns the writing phase missed

## When NOT to Use

- Writing tests from scratch (use `writing-unit-tests` skill instead)
- Debugging a test failure caused by production code (use `bugfix` or `root-cause-tracing`)
- Throwaway spike/prototype tests

## Scope Determination

```
What are you reviewing?
  Specific test file(s) → Review those files directly
  A PR/commit → Run git diff, extract test files from the changeset
  A package/directory → Glob for test files (*.test.*, *.spec.*, __tests__/**)
  Entire codebase → Start with git diff against main, then expand to full glob
```

For codebase-wide audits, prioritize: recently changed tests > tests for critical paths > everything else.

## Review Process

### Step 1: Determine Scope and Gather Context

Identify the test files under review and read the production code they target. You cannot review a test without understanding what it's supposed to verify.

### Step 2: Run the Companion Skills Check

Before manual review, invoke these companion skills and agents for their specialized analysis:

| Skill/Agent | What It Catches | How to Use |
|---|---|---|
| `testing-anti-patterns` skill | Mock behavior testing, test-only production methods, mocking without understanding, incomplete mocks | Apply its gate functions to every mock and assertion |
| `writing-unit-tests` skill | Implementation-testing, untestable code, mock overuse, poor isolation, skip hygiene | Apply its behavior-vs-implementation lens and test doubles hierarchy |
| `quality-reviewer` agent | Security issues in test fixtures, code quality, missing edge cases | Dispatch as subagent on the test files |
| `simplify` skill | Overly complex test setup, redundant assertions, unclear test structure | Invoke on the test files after other issues are fixed |

**Workflow:** Apply `testing-anti-patterns` + `writing-unit-tests` criteria first (test-specific), then dispatch `quality-reviewer` agent (general quality), then the `simplify` skill (cleanup).

### Step 3: Manual Review Against Checklist

After the companion analysis, review against the checklist below. Focus on issues the automated passes may miss — especially test design, coverage gaps, and semantic correctness.

## Review Checklist

### Assertions and Behavior

- [ ] Every assertion targets **observable behavior** (return values, state changes, side effects), not implementation details
- [ ] No assertions on mock existence (`getByTestId('*-mock')`)
- [ ] Test names describe the **behavior being verified**, not the method being called
- [ ] Tests verify **what**, not **how** — they survive internal refactors
- [ ] Edge cases and error paths are covered, not just the happy path
- [ ] Each test has a clear, single reason to fail

### Mocking and Test Doubles

- [ ] Fakes preferred over stubs, stubs over spies, spies over mocks
- [ ] Each mock has a **one-sentence justification** for why it exists
- [ ] Mock data mirrors **complete** real-world schemas (no partial mocks)
- [ ] Mock setup is proportional to test logic (not >50% of the test)
- [ ] No mocking of the unit under test
- [ ] Mocked side effects are understood — no "mock it to be safe"
- [ ] 4+ mocks in one test = signal the code needs refactoring, not more mocks

### Test Isolation and Structure

- [ ] Each test sets up its own state — no dependency on test execution order
- [ ] No shared mutable state across tests (reset in beforeEach or use fresh instances)
- [ ] Test cleanup is complete — no leaked state, listeners, or timers
- [ ] No duplicate cleanup (e.g., `afterEach` AND explicit call in the same test)
- [ ] Tests are deterministic — no reliance on wall-clock time, random values, or network
- [ ] Setup/teardown blocks are minimal and focused

### Coverage and Completeness

- [ ] Business logic and validation rules are tested, not incidentals (logging, metrics)
- [ ] Boundary conditions are exercised (empty inputs, null, max values, off-by-one)
- [ ] Error scenarios return correct error types/messages, not just "doesn't throw"
- [ ] Integration points are tested with real implementations where feasible

### Test Hygiene

- [ ] Skipped tests have a documented reason, tracking issue, and re-enable condition
- [ ] No mystery skips (`it.skip` without explanation)
- [ ] No commented-out tests (delete or restore with explanation)
- [ ] Test file organization mirrors production code structure
- [ ] No copy-paste test blocks with slight variations — extract parameterized tests or shared helpers

### Simplicity and Readability

- [ ] Test setup is under ~10 lines per test
- [ ] Test intent is clear within 5 seconds of reading
- [ ] No "clever" test utilities that obscure what's being tested
- [ ] Arrange-Act-Assert structure is evident
- [ ] Helper functions are named for **what they set up**, not `setupTest1`/`helper2`

## Red Flags — Escalate or Refactor

These patterns indicate the **production code** needs attention, not just the tests:

- Test requires 5+ dependencies to be mocked
- Test setup exceeds 20 lines of configuration
- Function under test has 10+ conditionals or early returns
- Test can only verify behavior by asserting on internal method calls
- Multiple tests need identical complex setup (missing test fixture or factory)

**Response:** Flag for refactoring. Better production design makes tests simpler.

## Output Format

Organize findings by severity, following the `quality-reviewer` agent convention:

- **CRITICAL**: Tests that give false confidence (passing when code is broken, asserting on mocks)
- **HIGH**: Anti-patterns that will cause maintenance pain (brittle mocks, implementation testing, missing edge cases)
- **SUGGESTIONS**: Readability and structure improvements
- **POSITIVE**: Well-written tests worth noting as patterns to follow

For each finding: file:line reference, the issue, and a concrete fix or the companion skill that addresses it.

## Quick Reference

| Smell | Signal | Fix |
|---|---|---|
| Mock behavior testing | Asserting on `*-mock` test IDs | Unmock or test real behavior |
| Implementation testing | `expect(mock).toHaveBeenCalledWith(...)` as main assertion | Assert on output/state instead |
| Test-only production methods | Method only called from test files | Move to test utilities |
| Incomplete mocks | Partial response objects | Mirror complete API schema |
| Over-mocking | 4+ mocks, setup > test logic | Refactor production code |
| Shared mutable state | Tests fail when run in isolation or different order | Fresh state per test |
| Mystery skips | `it.skip` without comment | Document reason + tracking issue |
| Copy-paste tests | Near-identical blocks with one param changed | Parameterized tests / `it.each` |
| Incidental testing | Asserting on log calls, metric emissions | Delete — test business logic |
| Misplaced tests | Test for unrelated module in this file | Move to correct test file |
| Flaky timing | `setTimeout`/`sleep` in tests | Use condition-based waiting |
