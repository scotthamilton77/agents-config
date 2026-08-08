---
name: grill-with-docs
description: Grilling session that challenges your plan against the existing domain model, sharpens terminology, and updates documentation (CONTEXT.md, ADRs) inline as decisions crystallise. Use when user wants to stress-test a plan against their project's language and documented decisions.
admission:
  prevents: An existing plan advancing to implementation while it still contradicts the project's glossary, ADRs, and code — the drift surfaces late as rework and human intervention.
  cost: Adds a standalone deep session that cross-checks every claim against CONTEXT.md/ADR docs and holds the plan until its acceptance criteria are enumerated.
  remove_when: The readiness gate can mechanically detect glossary/ADR contradictions and prove enumerated red-test-convertible acceptance criteria without this session having run.
---

<!--
Source: skills/engineering/grill-with-docs/
Upstream: https://github.com/mattpocock/skills @ ed37663cc5fbef691ddfecd080dff42f7e7e350d
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

What separates this session from a plain grilling is that it maintains the project's domain model as it goes, and the `domain-modeling` skill carries the mechanics for that: where the glossary and the decision records live in single- and multi-context repos, how to challenge a stated term against the recorded one, how to sharpen fuzzy language into a canonical term, and the three-part test a decision must pass before it earns an ADR.

**Invoke `domain-modeling` before you ask the first interview question.** Glossary entries and ADRs get written the moment a term or a decision crystallises rather than batched at the end, so the mechanics have to be in hand before the interview begins — not fetched partway through an answer.

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
