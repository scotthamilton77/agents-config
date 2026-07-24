---
name: grilling
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
admission:
  prevents: Implementation starting from a goals-only idea whose decisions and edge cases were never resolved, forcing rework and human babysitting downstream.
  cost: Front-loads a one-question-at-a-time interview and a terminal acceptance-criteria enumeration before any building begins.
  remove_when: The readiness gate can mechanically prove a plan enumerates red-test-convertible acceptance criteria without this interview having run.
---

<!--
Source: oss-snapshots/pocock/skills/skills/productivity/grilling/
Upstream: https://github.com/mattpocock/skills
Drift policy: local-fork — grafted, do not re-sync
-->

Interview me relentlessly about every aspect of this until we reach a shared understanding. Walk down each branch of the decision tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before continuing. Asking multiple questions at once is bewildering.

If a *fact* can be found by exploring the environment (filesystem, tools, etc.), look it up rather than asking me. The *decisions*, though, are mine — put each one to me and wait for my answer.

Do not act on it until I confirm we have reached a shared understanding.

## Exit criterion

The grilling session does not end until the plan's **acceptance criteria are enumerated with stable IDs**, and each one is stated so it is directly expressible as a *failing test* (red-test-convertible: a concrete observable that is false today and true when the work is done).

For every acceptance criterion, apply the edge-case taxonomy — surface and resolve, or explicitly rule out with a reason, each of:

- **Inverse case** — the negative/failure path, not just the happy path.
- **Empty / boundary input** — zero, empty, min, max, first, last.
- **Dependency failure** — an upstream tool, file, service, or precondition is absent or errors.
- **Repeated / concurrent invocation** — run twice, run in parallel, interleaved.
- **Idempotency** — a second identical run changes nothing beyond the first.

If any AC lacks an ID, cannot be phrased as a failing test, or has an unaddressed taxonomy row, the session is not done — keep grilling until it is.
