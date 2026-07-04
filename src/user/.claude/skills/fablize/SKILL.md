---
name: fablize
description: Use when a frontier-tier model is available for a limited window and the goal is to close spec gaps on backlog work before that window closes or the model becomes cost-prohibitive. Triggers on "fablize", "specfest", "spec out the backlog", "spec out beads", "close spec gaps before the model window closes", "get the backlog ready for a cheaper model", "make these tickets implementable by a lesser model", or any request to batch-produce design specs from thin backlog items while premium model capacity is available. Does not implement anything.
---

# fablize

## Overview

A "specfest": when the strongest available frontier model is at the helm for
a limited window — before it becomes unavailable or cost-prohibitive — spend
that window closing spec gaps on backlog work, not implementing it. The
output is design specs and implementation-ready backlog items that a cheaper
or lesser model can execute correctly later. The name is a legacy of one such
window; the mechanic is model-agnostic.

Fablize does not implement anything. It turns "I have frontier capacity for
N days" into a prioritized, batched, human-approved spec-writing pipeline.

Mind the token budget throughout — the whole premise is a scarce, expensive
resource; a phase that burns it on process rather than spec quality has
defeated the point.

## When to Use

- A temporary capability or budget window is closing and thin-spec backlog
  sits behind it.
- The user wants a batch of backlog items made implementation-ready without
  doing the implementation now.

## Phase 1 — Survey (autonomous, no approval needed)

1. **Learn what's already spec'd.** Check recent merged history for spec
   work, and read the project's dated-specs directory (`docs/specs/` by
   convention — detect the actual location, or ask, if this project differs)
   to learn the local spec-output pattern. Skip anything already carrying a
   merged spec — those items are usually already in progress.
2. **Collect the backlog.** Invoke the whats-next skill in `all` mode with no
   truncation, and pull the full open/deferred backlog from the work tracker.
3. **Measure spec coverage.** For each plausible candidate, pull its full
   record and gauge how much description, design rationale, and acceptance
   criteria it already carries. Classify each as **already-spec'd**
   (externalized spec doc, implementation-ready label, rich acceptance
   criteria) or **thin** (one-line description, no design, no AC). Check
   upstream dependency edges too — don't propose spec'ing something a blocked
   dependency makes structurally moot.

## Phase 2 — Select and present (ends in a hard STOP)

4. **Select a small batch.** Default 4–6 items; never propose more without
   the human explicitly asking for a bigger batch. Rank candidates by, in
   order:
   - (a) benefits most from a frontier pass — thin spec × high
     judgment-density (ambiguous scope, architectural trade-offs,
     cross-cutting design);
   - (b) container/priority standing in the roadmap;
   - (c) conceptual cohesion — one domain per batch, so the human reviewing
     spec output isn't context-switching between unrelated subsystems.
5. **Present the batch for approval.** Show: a table of the selected items
   (priority, roadmap position, evidence of the spec gap, title); the
   rejected alternative clusters with a one-line reason each; and these four
   questions:

   | # | Question |
   |---|---|
   | Q1 | Batch composition — confirm the set, or adjust it |
   | Q2 | Spec grouping — one dated spec per item, or grouped specs covering related items |
   | Q3 | End-state per item — spec merged + description/AC updated + a readiness label stamped, or leave labeling to a separate readiness gate |
   | Q4 | Involvement split — which items need interactive brainstorming with the human, and which can be spec'd autonomously |

6. **STOP.** Wait for the human's answers. Do not dispatch anything —
   interactive or autonomous — before this approval lands.

## Phase 3 — Execute (after approval)

7. **Interactive items** — brainstorm with the human one question at a time,
   each preceded by enough context that they can answer confidently without
   re-deriving it themselves.
8. **Autonomous items** — dispatch right-sized workers. Every dispatch names
   a model and an effort level explicitly: mechanical survey/extraction work
   goes to a cheap model at low effort, spec synthesis to a mid-tier model,
   judgment-dense synthesis (architecture, trade-off resolution) stays with
   the frontier model. If a frontier-tier worker itself needs to fan out
   further, that's nested dispatch — follow the orchestrating-subagents
   skill rather than letting the worker spawn a child it can't await.
9. **Deliver.** Per item (or per approved group): a dated design spec in the
   project's specs directory, following the local pattern; the item's
   description/acceptance criteria updated to point at the spec; a readiness
   label applied per the Q3 answer. Ship specs the same way the environment
   already ships everything else — through its normal completion-gate,
   worktree, and PR discipline; fablize doesn't restate that machinery, only
   feeds it.

## Red Flags

| Rationalization | Reality |
|---|---|
| "The batch could be a bit bigger" | No — human review time is the bottleneck, not model capacity. Default stays 4–6. |
| "This item's spec looks good enough" | Measure description/design/AC content per item; don't eyeball it. |
| "I'll skip the STOP and start spec'ing — the batch is obviously right" | Never. Phase 2 always ends in a stop; approval is not optional. |
| "One strong model can just implement this directly, why spec it" | That defeats the window argument: spec now while frontier capacity is available, implement later on whatever's cheap then. |
| "Mixed-domain batch is fine, they're all just backlog items" | Domain-mixing is the context-switch tax fablize exists to avoid; keep one domain per batch. |

## NOT For

- Implementing the work itself — fablize only produces specs and
  implementation-ready backlog items.
- Backlog items that already carry an adequate spec — those don't need a
  frontier pass.
- Substituting for the project's own readiness or verification gates —
  fablize feeds those gates, it doesn't replace them.
- Merging pull requests — spec output ships as a PR like anything else;
  fablize doesn't touch merge authority.
