# Test quality

What separates a test worth keeping from one that costs more than it earns.
Written for both seats: the agent about to write a test, and the agent judging
one someone else wrote.

## Contents

- [The one question](#the-one-question) — the tautology filter
- [Behaviour versus implementation](#behaviour-versus-implementation)
- [Test doubles](#test-doubles) — fake over stub over spy over mock
- [Where doubles belong, and how to design for them](#where-doubles-belong-and-how-to-design-for-them)
- [Refusal criteria](#refusal-criteria) — when not to write the test at all
- [Skip hygiene](#skip-hygiene)
- [Worked examples](#worked-examples)

## The one question

Before accepting any test, ask: **what coded decision does this pin?**

If the answer is "the literal I just typed" or "the language, the standard
library, or the operating system", the test is a tautology. It passes by
construction, it can never disagree with the code, and it will be maintained
forever. Delete it.

Three shapes to screen for.

### 1. Language, compiler, standard library or OS behaviour

A test that passes as long as the language is not broken is a comment with
ceremony.

| Reject | Why | Write instead |
|---|---|---|
| `isinstance(obj, SomeProtocol)` | Pins runtime name-matching, not your logic; the type checker already enforces the signature | A behaviour test through whatever consumes the object |
| A frozen record raising on assignment | Pins the standard library's immutability machinery | Nothing — the type system enforces it |
| A path helper returning false for a directory | Pins filesystem-library semantics, not your probe decision | "Given the config file is absent, auto-detect returns empty" — pins *your choice* of what to probe |

### 2. Code with no caller yet

If nothing in the current change invokes a function, a test for it pins the
return-value literal you just typed. That is a snapshot of your own code, and
it fails only when you edit the literal.

Mark the uncalled code excluded from coverage with a note naming the change
that will exercise it, and put the removal of that exclusion in that change's
criteria. Do not write coverage theatre to satisfy a gate.

### 3. Attribute and enum literals

Asserting `adapter.name == "claude"` against an implementation that reads
`name = "claude"` has exactly one failure mode: you changed the literal, and
the linter told you first. Pin constants at the **consumer boundary** — flag
parsing, config loading, the serialized output — where a wrong string breaks a
visible contract.

**Exception:** a public constant that forms part of a serialization contract
(written to disk, sent over the wire) is pinned at the serialization boundary,
not at its definition.

## Behaviour versus implementation

| | |
|---|---|
| **Good assertions** | Return values, observable state changes, side effects a caller can see |
| **Bad assertions** | "Method X was called", internal execution order, call counts |

A test coupled to implementation breaks when you refactor without changing
behaviour. That is the tell, and it is the whole diagnosis.

Do test: calculation correctness, validation rules, state transitions,
business-rule enforcement, error types and messages.

Do not test: logging calls, metric emissions, cache key formats, internal call
order. Asserting that a logger was called pins a decision nobody made
deliberately.

Verify **through the interface**, never around it. A test that writes through
the public API and then reads the database directly is testing two things and
proving neither.

## Test doubles

Prefer them in this order, and reach further down the list only when the one
above genuinely cannot work.

| Type | What it does | When |
|---|---|---|
| **Fake** | A simple working implementation | The default. A database becomes an in-memory map |
| **Stub** | Returns canned responses | External services with predictable responses |
| **Spy** | Records calls against a real object | Verifying a side effect that has no other observable trace |
| **Mock** | Asserts that specific calls happened | Almost never. Last resort |

A mock asserts on *how*, which is the thing a test is supposed not to care
about. Every mock in a test needs a one-sentence justification for why nothing
above it in the table would do.

**Mirror the complete structure, not the fields your test happens to read.** A
partial double hides a structural assumption: downstream code reaches for a
field you omitted, the test passes, and the integration fails. If your double
returns a response, you are claiming to understand the whole response.

## Where doubles belong, and how to design for them

Substitute at **system boundaries** only: external APIs, time, randomness,
sometimes the filesystem, sometimes the database — though a real test database
usually beats doubling one.

Do not double your own classes, internal collaborators, or anything you
control. Substituting something you own is a design signal, not a testing
technique.

Two habits make a boundary easy to double:

**Accept dependencies, do not construct them.** A function handed a payment
client is testable; one that builds a client from environment variables inside
itself is not.

**Prefer specific operations over one generic fetcher.** An interface with
`getUser`, `getOrders` and `createOrder` gives each double one shape to return.
A single `fetch(endpoint, options)` forces conditional logic inside the double,
which is a second implementation you now have to debug.

## Refusal criteria

**Refuse to write the test** when any of these hold:

- The function needs test doubles for **five or more** dependencies
- The function has ten or more conditionals or early returns
- Test setup would exceed twenty lines of double configuration
- You would be asserting "did method X get called" rather than "did it produce
  the right output"
- You have not read the code under test — loose matchers like
  `/completed|success|ok/i` are the tell

**Say so, in these terms:** "This code is not testable in its current form.
Let us decompose it into smaller units first, then test each one simply."

Five is the line in both directions: five doubles is where a test stops being
worth writing, and it is also the point at which the *production* code, not the
test, is what needs to change.

### When the refactor is blocked

If a constraint forbids the refactor — a separate ticket, a frozen API, a
pending review — and the code meets a refusal criterion:

1. **Do not ship anti-pattern tests to satisfy a coverage gate.** Coverage from
   a forest of doubles is theatre. It cements the design and buys permanent
   maintenance cost.
2. **Escalate.** File the blocker, ask for the refactor to be unblocked, or get
   an explicit waiver from whoever owns the code.
3. **Record the waiver where the reviewer will see it** — in the change
   description, not buried in a test comment. They need to know they are
   approving anti-pattern tests.

"I will file a follow-up to fix it later" is not a waiver. Deferred cleanup is
cleanup that does not happen.

## Skip hygiene

Treat every skip as debt that accrues interest.

```
Test is failing
 └─ Do you understand why?
     ├─ No  → investigate. Do not skip.
     └─ Yes → Can you fix it now?
               ├─ Yes → fix it
               └─ No  → Environment-specific?
                         ├─ Yes → exclude via config, and document where the
                         │        project keeps its testing notes
                         └─ No  → skip with a tracking reference and a deadline
```

Every skipped test carries three things: **a reason, a tracking reference, and
the condition that re-enables it.** A skip with a comment saying only that it is
skipped tells the next reader nothing about whether it is broken, obsolete, or
platform-specific.

| Red flag | What it usually means |
|---|---|
| Skip count rising over time | Tests are being abandoned, not fixed |
| Skips with no explanation | Nobody knows whether they are still relevant |
| Skips older than three months | Fix or delete; stale skips rot |
| A skip added in the same change as the code | Possibly hiding a regression |
| Skipping a "flaky" test | Often a real bug with a non-deterministic trigger |

## Worked examples

**Verify through the interface, not around it.**

```typescript
// BAD: bypasses the interface to check the result
test("createUser saves to database", async () => {
  await createUser({ name: "Alice" });
  const row = await db.query("SELECT * FROM users WHERE name = ?", ["Alice"]);
  expect(row).toBeDefined();
});

// GOOD: the interface is both the action and the observation
test("createUser makes the user retrievable", async () => {
  const user = await createUser({ name: "Alice" });
  expect((await getUser(user.id)).name).toBe("Alice");
});
```

**The expected value comes from outside the implementation.**

```typescript
// BAD: expected value is recomputed the way the code computes it, so the
// assertion agrees with the code no matter what either of them does
test("calculateTotal sums line items", () => {
  const items = [{ price: 10 }, { price: 5 }];
  expect(calculateTotal(items)).toBe(items.reduce((s, i) => s + i.price, 0));
});

// GOOD: an independent, known literal
test("calculateTotal sums line items", () => {
  expect(calculateTotal([{ price: 10 }, { price: 5 }])).toBe(15);
});
```

**Assert on the output, not on the call.**

```typescript
// BAD: pins that a method was called. Breaks on any internal change and
// proves nothing about correctness.
it("calls validator.validate with the card", async () => {
  await processor.processPayment(100, card);
  expect(mockValidator.validate).toHaveBeenCalledWith(card);
});

// GOOD: pins a business rule
it("caps commission at 50% of sales", () => {
  expect(calculateCommission(1000, { rate: 0.8 })).toBe(500);
});
```

**Each test owns its state.**

```typescript
// BAD: shared mutable state — test 2 fails, and only when test 1 ran first
let counter = 0;
beforeEach(() => { counter++; });
it("test 1", () => { expect(counter).toBe(1); });
it("test 2", () => { expect(counter).toBe(1); });

// GOOD: fresh state per test
it("increments from zero", () => {
  const counter = createCounter();
  counter.increment();
  expect(counter.value).toBe(1);
});
```
