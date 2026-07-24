---
name: to-spec
description: Turn the current conversation into a spec — no interview, just synthesis of what you've already discussed. Invoke when the user asks to turn the conversation into a spec.
admission:
  prevents: A resolved conversation evaporating into a goals-only or verbally-agreed plan that an implementer cannot execute without re-litigating decisions and edge cases.
  cost: Adds a synthesis pass that writes a dated spec whose output contract requires enumerated acceptance criteria and an ordered, AC-cited slice list before it is done.
  remove_when: The pipeline can mechanically emit an implementable spec with red-test-convertible acceptance criteria and sliced work from the conversation without this authoring step.
---

<!--
Source: oss-snapshots/pocock/skills/skills/engineering/to-spec/
Upstream: https://github.com/mattpocock/skills
Drift policy: local-fork — grafted, do not re-sync
-->

This skill takes the current conversation context and codebase understanding and produces a spec (you may know this document as a PRD). Do NOT interview the user — just synthesize what you already know.

## Process

1. Explore the repo to understand the current state of the codebase, if you haven't already. Use the project's domain glossary vocabulary throughout the spec, and respect any ADRs in the area you're touching.

2. Sketch out the seams at which you're going to test the feature. Existing seams should be preferred to new ones. Use the highest seam possible. If new seams are needed, propose them at the highest point you can. The fewer seams across the codebase, the better — the ideal number is one.

Check with the user that these seams match their expectations.

3. Write the spec using the template below and save it as a dated file (`YYYY-MM-DD-<slug>.md`) in the project's spec home. Publishing work items to the issue tracker is a separate step and out of scope here.

<spec-template>

## Problem Statement

The problem that the user is facing, from the user's perspective.

## Solution

The solution to the problem, from the user's perspective.

## User Stories

A LONG, numbered list of user stories. Each in the format: `As an <actor>, I want a <feature>, so that <benefit>`. Cover all aspects of the feature.

## Implementation Decisions

The modules built/modified, their interfaces, technical clarifications, architectural decisions, schema changes, API contracts, specific interactions. Do NOT include file paths or code snippets — they go stale fast. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose (state machine, reducer, schema, type shape), inline the decision-rich bits and note it came from a prototype.

## Testing Decisions

What makes a good test (only external behavior, not implementation details), which modules will be tested, and prior art for the tests.

## Acceptance Criteria

A numbered list of acceptance criteria, each with a **stable ID** (`<ID>` matches `[A-Z0-9]+-[A-Z]\d+` or `AC\d+`, e.g. `AC1`, `FOO-A1`). Each criterion MUST be **red-test-convertible**: stated as a concrete observable that is false today and true when the work is done, so it maps to one failing test.

For every criterion, apply the edge-case taxonomy — resolve or explicitly rule out each of: **inverse case** (failure path), **empty/boundary input** (zero, empty, min, max), **dependency failure** (an upstream tool/file/service absent or erroring), **repeated/concurrent invocation**, and **idempotency** (a second identical run changes nothing).

## Ordered Slice List

An ordered list of slices. Each slice is the **smallest independently mergeable** unit of work and **cites the acceptance-criterion IDs it satisfies**. Order so each slice's dependencies land before it.

**Size tripwire:** if the spec exceeds **400 lines** or **8 slices**, split it into a parent spec plus child specs (one child per coherent slice group), each child carrying its own Acceptance Criteria and Ordered Slice List.

## Out of Scope

The things that are out of scope for this spec.

## Further Notes

Any further notes about the feature.

</spec-template>
