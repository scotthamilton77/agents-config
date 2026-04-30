---
name: writing-unit-tests
model: sonnet
argument-hint: "[file or function to test]"
description: Use when writing or reviewing unit tests, when test setup balloons with mocks, when CI coverage gates are pressuring anti-pattern tests, or when code resists testing — covers behavior-vs-implementation, fakes/stubs/spies/mocks hierarchy, refusal criteria, and rationalizations to reject
---

# Writing Unit Tests

## Core Principle

If you can't test it simply, the code needs refactoring — not more mocks. Test behavior, not implementation.

## When to Use

- About to write or modify a unit test file
- Reviewing test code in a PR or commit
- Asked to add tests to existing code (especially legacy or complex)
- A coverage gate is pressuring you to ship tests
- Tempted to add mocks to make a test pass

## When NOT to Use

- Throwaway prototypes or spikes — write whatever lets you learn faster
- Generated code (e.g. ORM scaffolding) where the generator owns correctness
- Pure config files with no logic
- Integration / E2E tests — different discipline; this skill is unit-level

## The Iron Laws

```
1. TEST BEHAVIOR, NOT IMPLEMENTATION
2. REFUSE TO TEST UNTESTABLE CODE—REFACTOR FIRST
3. MOCKS ARE A SMELL, NOT A SOLUTION
```

**Violating the letter of these laws is violating the spirit.** Naming a method `*ForTesting`, casting mocks to `any`, using regex matchers on outputs you haven't read, or filing a "follow-up to fix it later" are all violations dressed up as compliance. The discipline applies to intent, not syntax.

## Refusal Criteria

**REFUSE to write tests when:**

- Function has 5+ dependencies requiring mocks
- Function has 10+ conditionals or early returns
- Test setup exceeds 20 lines of mock configuration
- You're testing "did method X get called" instead of "did it produce correct output"
- You haven't read the code under test (loose regex matchers like `/completed|success|ok/i` are a tell)

**Response:** "This code isn't testable in its current form. Let's refactor into smaller units first, then test each unit simply."

### When refactor is blocked

If a constraint says you can't refactor (separate ticket, frozen API, blocked on review) AND the code meets a refusal criterion:

1. **Do NOT ship anti-pattern tests to satisfy a coverage gate.** Coverage from mock-forest tests is theater — it cements bad design and creates permanent maintenance burden.
2. **Escalate**: file a blocker, request the refactor ticket be unblocked, or get an explicit waiver from the owning engineer that anti-pattern tests are acceptable for this PR.
3. **Document the waiver in the PR description**, not buried in test comments. The reviewer needs to know they're approving anti-pattern tests, not careful TDD.

"I'll file a follow-up bead to fix it later" is not a waiver. It's deferred cost that historically never gets paid.

## Behavior vs Implementation

**GOOD assertions:** Output/return value, observable state change
**BAD assertions:** Method X was called, internal execution order, call counts (`toHaveBeenCalledTimes`)

### Good: Behavior Tests

```typescript
it('returns full name when no nickname', () => {
  const user = { firstName: 'Jane', lastName: 'Doe' };
  expect(formatDisplayName(user)).toBe('Jane Doe');
});

it('returns nickname when present', () => {
  const user = { firstName: 'Jane', lastName: 'Doe', nickname: 'JD' };
  expect(formatDisplayName(user)).toBe('JD');
});
```

Tests actual output. Survives any refactor that preserves behavior.

### Bad: Implementation Tests

```typescript
it('should call validator.validate with card', async () => {
  mockValidator.validate.mockResolvedValue(true);
  await processor.processPayment(100, card);
  expect(mockValidator.validate).toHaveBeenCalledWith(card);
});
```

Tests that code calls a method. Breaks on any internal change. Proves nothing about correctness.

## Test Doubles

| Type | What It Does | When to Use |
|------|--------------|-------------|
| **Fake** | Simple working implementation | Default choice — database → in-memory map |
| **Stub** | Returns canned responses | External services with predictable responses |
| **Spy** | Records calls to real object | Verifying side effects (analytics, logging) |
| **Mock** | Verifies specific calls | Almost never — last resort |

If you need 5+ mocks, the code is too coupled. Refactor it. (This matches the Refusal Criteria threshold above — same "too coupled" line, different framing.) See `testing-anti-patterns` for the dedicated mock/fake/spy/stub anti-pattern catalog.

## Test Isolation

Each test must set up its own state, not depend on other tests, and not leave state that affects other tests.

```typescript
// BAD: Shared mutable state
let counter = 0;
beforeEach(() => { counter++; });
it('test 1', () => { expect(counter).toBe(1); }); // Passes first
it('test 2', () => { expect(counter).toBe(1); }); // Fails!

// GOOD: Fresh state per test
it('test 1', () => {
  const counter = createCounter();
  counter.increment();
  expect(counter.value).toBe(1);
});
```

## Business Logic vs Incidentals

**Test:** calculation correctness, validation rules, state transitions, business rule enforcement. **Don't test:** logging calls, metric tracking, cache key formats, internal method call order.

```typescript
// GOOD: Tests business rule
it('caps commission at 50% of sales', () => {
  const commission = calculateCommission(1000, { rate: 0.8 });
  expect(commission).toBe(500); // Capped, not 800
});

// BAD: Tests logging
it('should log when processing', async () => {
  await processOrder(order);
  expect(mockLogger.info).toHaveBeenCalledWith('Processing order');
});
```

## Refactoring for Testability

When code is untestable, decompose it:

```typescript
// BEFORE: Untestable monolith
async function processOrder(order, db, cache, logger, metrics, notifications) {
  // 200 lines mixing everything
}

// AFTER: Testable units
function validateOrder(order: Order): ValidationResult { /* pure */ }
function calculateTotal(items: Item[], discount: number): number { /* pure */ }

// Integration just wires them together
async function processOrder(order: Order, deps: OrderDeps): Promise<Result> {
  const validation = validateOrder(order);
  if (!validation.valid) return { error: validation.error };
  const total = calculateTotal(order.items, order.discount);
  // etc.
}
```

Each pure function is trivial to test. Integration test verifies wiring.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Team pattern requires mocking everything" | Bad patterns don't become good through repetition. Push back. |
| "Just match the existing test pattern" | Existing patterns aren't justification — they're inheritance of past bad decisions. Escalate, don't comply. |
| "Need 90% coverage by EOD" | Coverage without behavior verification is theater. |
| "Coverage gate is 80% — gotta hit it" | Hitting a number with mock-forest tests is fraud against your own future self. Escalate the gate. |
| "It's already in production" | Sunk cost. Cementing bad design costs more long-term. |
| "Just a quick test" | Quick bad test = permanent maintenance burden. |
| "Don't have time to refactor" | Time to write mock forest > time to extract pure function. |
| "Can't refactor — separate ticket / blocked" | Then refuse the test. Shipping anti-pattern tests under a refactor block is worse than shipping no tests. Escalate. |
| "I'll file a follow-up bead to fix it later" | Deferred cleanup is cleanup that won't happen. The follow-up is a graveyard. Refuse now or do it now. |
| "Loose regex matchers are fine — I haven't read the function" | Then you're not writing a test, you're writing a snapshot. Read the code first or refuse. |
| "`as any` to dodge typing six fakes is fine under deadline" | If the mock won't typecheck, the mock is wrong. `as any` hides the truth. |

## Red Flags — STOP

If you're about to:

- Write `expect(mock.method).toHaveBeenCalledWith(...)` as your main assertion
- Assert on call counts (`toHaveBeenCalledTimes(N)`) as primary verification
- Create 5+ mocks in `beforeEach`
- Cast mocks to `any` to make them typecheck
- Use loose regex matchers (`/completed|success|ok/i`) on outputs because you haven't read the function
- Write 20+ lines of test setup
- Test that internal methods were called in order
- Add tests to code you know is poorly structured
- Justify the test by "matching the team's existing pattern"
- Tell yourself "I'll file a follow-up bead to clean this up"

**STOP. Propose refactoring instead, or escalate the constraint.**

## Test Suppression and Exclusion

Treat every skip as technical debt that accrues interest.

### Decision Tree

```
Test is failing →
  Do you understand why? → NO → INVESTIGATE FIRST (don't skip)
  Do you understand why? → YES →
    Can you fix it now? → YES → Fix it
    Can you fix it now? → NO →
      Environment-specific? → YES → Exclude via config, document in AGENTS.md
      Environment-specific? → NO → Skip with issue link + deadline
```

### Skip Hygiene

Every skipped test MUST have: a reason, a tracking issue, and a condition for re-enabling.

```typescript
// GOOD: Documented skip with actionable context
it.skip('connects via Unix socket (sandbox blocks EPERM)', () => {
  // See AGENTS.md §sandbox_testing
  // Re-enable: run with INTEGRATION_TESTS=1 outside sandbox
});

// BAD: Mystery skip
it.skip('validates user input', () => {
  // No explanation—is this broken? obsolete? platform-specific?
});
```

### Red Flags for Test Suppression

| Red Flag | What It Usually Means |
|----------|----------------------|
| Skip count increasing over time | Tests are being abandoned, not fixed |
| Skips without explanations | No one knows if they're still relevant |
| Skips older than 3 months | Either fix or delete — stale skips rot |
| `skip` added in same PR as code change | Possibly hiding a regression |
| Skipping "flaky" tests | Often real bugs with non-deterministic triggers |

## Verification Checklist

Before submitting tests:

- [ ] Tests verify outputs/behavior, not method calls or call counts
- [ ] Each test name describes the behavior being verified
- [ ] Tests use fakes over mocks where possible
- [ ] No test depends on another test's execution
- [ ] Setup is under 10 lines per test
- [ ] No `as any` casts on test doubles
- [ ] No regex matchers covering for unread production code
- [ ] Would these tests survive an internal refactor?
- [ ] Any skipped tests have documented reasons and tracking issues

Can't check all boxes? Refactor the code, refuse the test, or escalate the constraint.
