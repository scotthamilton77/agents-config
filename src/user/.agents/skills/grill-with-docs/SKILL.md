---
name: grill-with-docs
description: Grilling session that challenges your plan against the existing domain model, sharpens terminology, and updates documentation (CONTEXT.md, ADRs) inline as decisions crystallise. Use when user wants to stress-test a plan against their project's language and documented decisions.
admission:
  prevents: An existing plan advancing to implementation while it still contradicts the project's glossary, ADRs, and code — the drift surfaces late as rework and human intervention.
  cost: Adds a standalone deep session that cross-checks every claim against CONTEXT.md/ADR docs and holds the plan until its acceptance criteria are enumerated.
  remove_when: The readiness gate can mechanically detect glossary/ADR contradictions and prove enumerated red-test-convertible acceptance criteria without this session having run.
---

<!--
Source: oss-snapshots/pocock/skills/skills/engineering/grill-with-docs/
Upstream: https://github.com/mattpocock/skills @ e74f0061bb67222181640effa98c675bdb2fdaa7
Last sync: 2026-05-23
Drift policy: local-fork — grafted, do not re-sync
Note: promoted from byte-identical local copy at <repo>/.claude/skills/grill-with-docs/.
-->

<what-to-do>

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before continuing.

If a question can be answered by exploring the codebase, explore the codebase instead.

</what-to-do>

<supporting-info>

## Domain awareness

During codebase exploration, also look for existing documentation:

### File structure

Most repos have a single context:

```
/
├── CONTEXT.md
├── docs/
│   └── adr/
│       ├── 0001-event-sourced-orders.md
│       └── 0002-postgres-for-write-model.md
└── src/
```

If a `CONTEXT-MAP.md` exists at the root, the repo has multiple contexts. The map points to where each one lives:

```
/
├── CONTEXT-MAP.md
├── docs/
│   └── adr/                          ← system-wide decisions
├── src/
│   ├── ordering/
│   │   ├── CONTEXT.md
│   │   └── docs/adr/                 ← context-specific decisions
│   └── billing/
│       ├── CONTEXT.md
│       └── docs/adr/
```

Create files lazily — only when you have something to write. If no `CONTEXT.md` exists, create one when the first term is resolved. If no `docs/adr/` exists, create it when the first ADR is needed.

## During the session

### Challenge against the glossary

When the user uses a term that conflicts with the existing language in `CONTEXT.md`, call it out immediately. "Your glossary defines 'cancellation' as X, but you seem to mean Y — which is it?"

### Sharpen fuzzy language

When the user uses vague or overloaded terms, propose a precise canonical term. "You're saying 'account' — do you mean the Customer or the User? Those are different things."

### Discuss concrete scenarios

When domain relationships are being discussed, stress-test them with specific scenarios. Invent scenarios that probe edge cases and force the user to be precise about the boundaries between concepts.

### Cross-reference with code

When the user states how something works, check whether the code agrees. If you find a contradiction, surface it: "Your code cancels entire Orders, but you just said partial cancellation is possible — which is right?"

### Update CONTEXT.md inline

When a term is resolved, update `CONTEXT.md` right there. Don't batch these up — capture them as they happen. Use the format in [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md).

`CONTEXT.md` should be totally devoid of implementation details. Do not treat `CONTEXT.md` as a spec, a scratch pad, or a repository for implementation decisions. It is a glossary and nothing else.

### Offer ADRs sparingly

Only offer to create an ADR when all three are true:

1. **Hard to reverse** — the cost of changing your mind later is meaningful
2. **Surprising without context** — a future reader will wonder "why did they do it this way?"
3. **The result of a real trade-off** — there were genuine alternatives and you picked one for specific reasons

If any of the three is missing, skip the ADR. Use the format in [ADR-FORMAT.md](./ADR-FORMAT.md).

## Exit criterion

A deep session against the docs does not end at glossary agreement. It ends only when the plan's **acceptance criteria are enumerated with stable IDs**, each one stated so it is directly expressible as a *failing test* (red-test-convertible: a concrete observable — false today, true when the work is done — that a reader can check against the code and the docs).

For every acceptance criterion, apply the edge-case taxonomy — surface and resolve, or explicitly rule out with a reason, each of:

- **Inverse case** — the negative/failure path, not just the happy path.
- **Empty / boundary input** — zero, empty, min, max, first, last.
- **Dependency failure** — an upstream tool, file, service, or precondition is absent or errors.
- **Repeated / concurrent invocation** — run twice, run in parallel, interleaved.
- **Idempotency** — a second identical run changes nothing beyond the first.

Cross-check each criterion against `CONTEXT.md` and the ADRs as you go: an AC that contradicts the recorded glossary or a documented decision is not done — resolve the contradiction (update the docs or revise the AC) before the session ends. If any AC lacks an ID, cannot be phrased as a failing test, or has an unaddressed taxonomy row, keep grilling until it can.

</supporting-info>
