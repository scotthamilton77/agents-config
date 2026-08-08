---
name: grill-with-docs
description: Grilling session that challenges your plan against the existing domain model, sharpens terminology, and updates documentation (CONTEXT.md, ADRs) inline as decisions crystallise. Use when user wants to stress-test a plan against their project's language and documented decisions.
admission:
  prevents: An existing plan advancing to implementation while it still contradicts the project's glossary, ADRs, and code — the drift surfaces late as rework and human intervention.
  cost: Adds a deep session that runs the grilling interview with the domain model attached, cross-checking every claim against CONTEXT.md/ADR docs and holding the plan until its acceptance criteria are enumerated.
  remove_when: The readiness gate can mechanically detect glossary/ADR contradictions and prove enumerated red-test-convertible acceptance criteria without this session having run.
---

<!--
Source: skills/engineering/grill-with-docs/
Upstream: https://github.com/mattpocock/skills @ 84fdeffd12f2ee307994d1eb6feb48173b6e0502
Last sync: 2026-08-07
Drift policy: selective-amalgamation — upstream's dispatcher shape is adopted, but the domain-model entry point and the docs cross-check on the exit criterion are local additions a byte-for-byte resync would revert. Take upstream changes selectively.
-->

**Invoke `grilling` at the start of this session.** The interview itself — the design tree, the rounds, the question frontier, and the acceptance-criteria exit criterion — lives in that skill, which this one composes rather than restates.

## Domain awareness

What separates this session from a plain grilling is that it maintains the project's domain model as it goes, and the `domain-modeling` skill carries the mechanics for that: where the glossary and the decision records live in single- and multi-context repos, how to challenge a stated term against the recorded one, how to sharpen fuzzy language into a canonical term, and the three-part test a decision must pass before it earns an ADR.

**Invoke `domain-modeling` before you ask the first interview question.** Glossary entries and ADRs get written the moment a term or a decision crystallises rather than batched at the end, so the mechanics have to be in hand before the interview begins — not fetched partway through an answer.

## What this session adds to the exit criterion

`grilling` already refuses to end until every acceptance criterion carries a stable ID, is expressible as a failing test, and has each edge-case taxonomy row resolved or ruled out. This session adds one condition to each of those criteria: cross-check it against `CONTEXT.md` and the ADRs as you go. A criterion that contradicts the recorded glossary or a documented decision is not done — resolve the contradiction, by updating the docs or by revising the criterion, before the session ends.
