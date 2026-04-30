---
name: testing-anti-patterns
model: sonnet
user-invocable: false
description: Use when writing or changing tests, adding mocks, asserting on mock-rendered elements, considering a test-only method on a production class, or tempted to mock "to be safe" without understanding the dependency
---

# Testing Anti-Patterns

**Core principle:** Tests must verify real behavior, not mock behavior. Mocks isolate — they are never the thing under test.

## The Iron Laws

```
1. NEVER test mock behavior
2. NEVER add test-only methods to production classes
3. NEVER mock without understanding dependencies
```

**Violating the letter of these laws is violating the spirit.** Naming a method `*ForTesting`, marking it `@internal`, or hiding it behind a "social contract" comment is still adding a test-only method. Asserting on any `*-mock` test id (e.g. `getByTestId('sidebar-mock')`) to "confirm setup worked" is still testing mock behavior. The discipline applies to intent, not syntax.

## When to Use

- Writing or modifying tests that require any test double (fake, stub, spy, mock)
- Adding test cleanup that needs to reach into a production object
- About to assert on a child component, mock element, or test-id
- Tempted to add a method to a production class that only tests will call
- Reviewing test code where mocks dominate the file

## When NOT to Use

- **Throwaway prototypes or spikes** — mock freely when exploring; discard code after
- **Testing the mock library itself** — if you maintain a mock/stub framework, testing mock behavior is the point
- **Contracts already enforced by types** — if the type system guarantees the structure, a gate-function check is overhead

## Anti-Pattern 1: Testing Mock Behavior

**The violation:**

```typescript
// BAD: Testing that the mock exists
test('renders sidebar', () => {
  render(<Page />);
  expect(screen.getByTestId('sidebar-mock')).toBeInTheDocument();
});
```

**Why this is wrong:**

- You're verifying the mock works, not that the component works
- Test passes when mock is present, fails when it's not
- Tells you nothing about real behavior

**Ask yourself:** "Am I testing the behavior of a mock?"

**The fix:**

```typescript
// GOOD: Test real component or don't mock it
test('renders sidebar', () => {
  render(<Page />);  // Don't mock sidebar
  expect(screen.getByRole('navigation')).toBeInTheDocument();
});

// OR if sidebar must be mocked for isolation:
// Don't assert on the mock - test Page's behavior with sidebar present
```

**Stubbing vs. asserting on stubs (critical distinction):**

It is fine to mock `<Sidebar>` so the test runs fast and deterministically. It is NOT fine to then assert `expect(screen.getByTestId('sidebar-mock')).toBeInTheDocument()`. The mock exists to silence the dependency, not to be the subject of an assertion. If `<Sidebar>` rendering matters to the test, do not mock it. If it doesn't matter, mock it silently and assert on `<Page>`'s own contract.

A test name like *"mounts Sidebar without hitting the network"* is a smell — it's verifying the mock worked, not the page worked.

### Gate Function

```
BEFORE asserting on any mock element:
  Ask: "Am I testing real component behavior or just mock existence?"

  IF testing mock existence:
    STOP - Delete the assertion or unmock the component

  Test real behavior instead
```

## Anti-Pattern 2: Test-Only Methods in Production

**The violation:**

```typescript
// BAD: destroy() only used in tests
class Session {
  async destroy() {
    // Looks like production API!
    await this._workspaceManager?.destroyWorkspace(this.id);
    // ... cleanup
  }
}

// In tests
afterEach(() => session.destroy());
```

**Why this is wrong:**

- Production class polluted with test-only code
- Dangerous if accidentally called in production
- Violates YAGNI and separation of concerns
- Confuses object lifecycle with entity lifecycle

**Common dressed-up violations (all still anti-patterns):**

- `destroyForTesting()` — the suffix is a wish, not a guard. Public methods are callable from anywhere.
- `@internal` JSDoc — comments are not enforcement. A determined or distracted caller will still invoke it.
- "Social contract" naming — there is no contract. There is only what types and module boundaries enforce.

If your test needs to clean up a workspace, **call the underlying manager from the test directly**:

```typescript
// GOOD: Test reaches the manager directly — no production API change needed
afterEach(async () => {
  await workspaceManager.destroyWorkspace(session.id);
});
```

"Reaching past the abstraction" is the *correct* move for test cleanup. The abstraction protects production callers from accidentally tearing down state — your `afterEach` is supposed to tear down state.

If the cleanup logic is reused across many test files, hoist it into a shared `test-utils/cleanupSession.ts` helper — but the helper still calls `workspaceManager.destroyWorkspace`, never anything on `Session` itself.

### Gate Function

```
BEFORE adding any method to production class:
  Ask: "Is this only used by tests?"

  IF yes:
    STOP - Don't add it
    Renaming it (*ForTesting, _internal, @internal) does NOT exempt it
    Put it in test utilities instead, or call the underlying API from the test

  Ask: "Does this class own this resource's lifecycle in production?"

  IF no:
    STOP - Wrong class for this method
```

## Anti-Pattern 3: Mocking Without Understanding

**The violation:**

```typescript
// BAD: Mock breaks test logic
test('detects duplicate server', () => {
  // Mock prevents config write that test depends on!
  vi.mock('ToolCatalog', () => ({
    discoverAndCacheTools: vi.fn().mockResolvedValue(undefined),
  }));

  await addServer(config);
  await addServer(config); // Should throw - but won't!
});
```

**Why this is wrong:**

- Mocked method had side effect test depended on (writing config)
- Over-mocking to "be safe" breaks actual behavior
- Test passes for wrong reason or fails mysteriously

**The fix:**

```typescript
// GOOD: Mock at correct level
test('detects duplicate server', () => {
  // Mock the slow part, preserve behavior test needs
  vi.mock('MCPServerManager'); // Just mock slow server startup

  await addServer(config); // Config written
  await addServer(config); // Duplicate detected
});
```

### Gate Function

```
BEFORE mocking any method:
  STOP - Don't mock yet

  1. Ask: "What side effects does the real method have?"
  2. Ask: "Does this test depend on any of those side effects?"
  3. Ask: "Do I fully understand what this test needs?"

  IF depends on side effects:
    Mock at lower level (the actual slow/external operation)
    OR use test doubles that preserve necessary behavior
    NOT the high-level method the test depends on

  IF unsure what test depends on:
    Run test with real implementation FIRST
    Observe what actually needs to happen
    THEN add minimal mocking at the right level

  Red flags:
    - "I'll mock this to be safe"
    - "This might be slow, better mock it"
    - Mocking without understanding the dependency chain
```

## Anti-Pattern 4: Incomplete Mocks

**The violation:**

```typescript
// BAD: Partial mock - only fields you think you need
const mockResponse = {
  status: 'success',
  data: { userId: '123', name: 'Alice' },
  // Missing: metadata that downstream code uses
};

// Later: breaks when code accesses response.metadata.requestId
```

**Why this is wrong:**

- **Partial mocks hide structural assumptions** - You only mocked fields you know about
- **Downstream code may depend on fields you didn't include** - Silent failures
- **Tests pass but integration fails** - Mock incomplete, real API complete
- **False confidence** - Test proves nothing about real behavior

**The Iron Rule:** Mock the COMPLETE data structure as it exists in reality, not just fields your immediate test uses.

**The fix:**

```typescript
// GOOD: Mirror real API completeness
const mockResponse = {
  status: 'success',
  data: { userId: '123', name: 'Alice' },
  metadata: { requestId: 'req-789', timestamp: 1234567890 },
  // All fields real API returns
};
```

### Gate Function

```
BEFORE creating mock responses:
  Check: "What fields does the real API response contain?"

  Actions:
    1. Examine actual API response from docs/examples
    2. Include ALL fields system might consume downstream
    3. Verify mock matches real response schema completely

  Critical:
    If you're creating a mock, you must understand the ENTIRE structure
    Partial mocks fail silently when code depends on omitted fields

  If uncertain: Include all documented fields
```

## When Mocks Become Too Complex

**Warning signs:**

- Mock setup longer than test logic
- Mocking everything to make test pass
- Mocks missing methods real components have
- Test breaks when mock changes

**Ask yourself:** "Do we need to be using a mock here?"

**Consider:** Integration tests with real components often simpler than complex mocks

## TDD as Prevention

Most of these anti-patterns evaporate under strict test-first discipline (write the test, watch it fail, write the minimum to pass, refactor). When you write the test before the implementation, you cannot "mock to be safe" — you do not yet know what the dependencies should look like, so you discover them by writing real ones first. Mocks introduced retroactively to make existing code testable are the breeding ground for these anti-patterns.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "I'll mock the children to be safe / for isolation" | Stubbing for isolation is fine. *Asserting* on the stub is the anti-pattern. Stub silently, assert on real behavior. |
| "Asserting `getByTestId('sidebar-mock')` confirms my mock setup worked" | Setup is verified by the test running. An assertion on the mock is testing mock behavior — Anti-Pattern 1. |
| "The clean option requires reaching past the abstraction — that's bad design" | For test cleanup, reaching past the abstraction is the *right* move. Production-grade encapsulation is for production callers, not your `afterEach`. |
| "`*ForTesting` suffix means production won't call it" | The suffix is a wish, not a guard. Public methods are callable from anywhere. |
| "`@internal` JSDoc / social contract is enough" | Comments do not enforce anything. Only types and module boundaries do. |
| "Mocking the slow stuff just to be safe" | "To be safe" without understanding what the real method does is Anti-Pattern 3. Run the real implementation first to learn what the test depends on. |
| "Partial mock — I only included the fields I use" | Anti-Pattern 4. Downstream code may consume fields you didn't mock. Mirror the full schema. |
| "The test is brittle but coverage is the priority" | Brittle tests are negative leverage — they break on legitimate refactors and erode trust. Refuse, don't ship. |

## Quick Reference

| Anti-Pattern                    | Fix                                           |
| ------------------------------- | --------------------------------------------- |
| Assert on mock elements         | Test real component or unmock it              |
| Test-only methods in production | Move to test utilities, or call the underlying API from the test directly |
| `*ForTesting` / `@internal` exemption | Doesn't exempt anything — same anti-pattern |
| Mock without understanding      | Understand dependencies first, mock minimally |
| Incomplete mocks                | Mirror real API completely                    |
| Over-complex mocks              | Consider integration tests                    |

## Red Flags

- Assertion checks for `*-mock` test IDs
- Methods only called in test files (regardless of name suffix or JSDoc)
- Mock setup is >50% of test
- Test fails when you remove mock
- Can't explain in one sentence why each mock exists
- Mocking "just to be safe"
- Test name describes the mock, not the behavior (e.g. "renders sidebar mock")

## Verification Checklist

Before considering test code complete, confirm:

- [ ] Every assertion targets real behavior, not mock presence
- [ ] No production method exists solely for test use (suffix/JSDoc do not exempt)
- [ ] Each mock's side effects are understood and accounted for
- [ ] Mock data structures mirror complete real-world schemas
- [ ] Mock setup is shorter than (or proportional to) test logic
- [ ] You can explain in one sentence why each mock exists
- [ ] Tests fail when the feature under test is broken (not just when mocks change)

## Companion Skill

For the constructive side — what *good* unit tests look like, refusal criteria, the test-doubles hierarchy — see the `writing-unit-tests` skill.
