---
name: grilling
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
admission:
  prevents: Implementation starting from a goals-only idea whose decisions and edge cases were never resolved, forcing rework and human babysitting downstream.
  cost: Front-loads a multi-round interview — one user round-trip per frontier, plus subagent fact-finding — and a terminal acceptance-criteria enumeration, before any building begins.
  remove_when: The readiness gate can mechanically prove a plan enumerates red-test-convertible acceptance criteria without this interview having run.
---

<!--
Source: skills/productivity/grilling/
Upstream: https://github.com/mattpocock/skills @ 84fdeffd12f2ee307994d1eb6feb48173b6e0502
Last sync: 2026-08-07
Drift policy: selective-amalgamation — upstream's design-tree/round/frontier machinery is grafted onto a local exit criterion (acceptance-criteria IDs plus the edge-case taxonomy) that upstream does not carry. A byte-for-byte resync would revert the exit criterion; take upstream changes selectively.
-->

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **question frontier** is every decision whose prerequisites are already settled — the questions you can ask *now* without guessing at answers you have not heard yet. Ask the whole question frontier in one round: number each question and give your recommended answer. Then wait for the user's answers before the next round. (The qualifier matters: this frontier is *questions that are answerable*, not work that is startable.)

Format each question like this, as Markdown in your reply rather than inside a code block:

❓ **Q1** - **Question title**: question body, possibly several paragraphs, including any multiple choices.

➡️ Your recommended answer

Each round of answers reshapes the tree — settled decisions push the question frontier outward and unblock the questions that depended on them. Recompute it, then ask the next round. A question whose answer depends on another question still open in this round belongs to a *later* round, not this one.

Finding *facts* is your job, never the user's. When a frontier question needs a fact from the environment (filesystem, tools, docs), dispatch a subagent to find it rather than asking the user for anything you could look up yourself. Do not block the round on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for that subagent to report — ask the rest of the question frontier now. The *decisions* are the user's: put each one to them and wait.

## Exit criterion

An empty question frontier is necessary but not sufficient. The session does not end until the plan's **acceptance criteria are enumerated with stable IDs**, each one stated so it is directly expressible as a *failing test* (red-test-convertible: a concrete observable that is false today and true when the work is done).

Those criteria are branches of the same tree, not a checklist bolted onto the end. For every acceptance criterion, each row of the edge-case taxonomy is itself a question on the frontier — resolve it, or explicitly rule it out with a reason:

- **Inverse case** — the negative/failure path, not just the happy path.
- **Empty / boundary input** — zero, empty, min, max, first, last.
- **Dependency failure** — an upstream tool, file, service, or precondition is absent or errors.
- **Repeated / concurrent invocation** — run twice, run in parallel, interleaved.
- **Idempotency** — a second identical run changes nothing beyond the first.

If any criterion lacks an ID, cannot be phrased as a failing test, or has an unaddressed taxonomy row, the frontier is not empty — keep grilling. Do not act on the plan until the user confirms you have reached a shared understanding.
