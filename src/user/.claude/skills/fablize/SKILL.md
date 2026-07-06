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

## Phase 0 — Model Check (fail fast)

Before Phase 1, confirm the window's premise still holds — fablize only pays
off when frontier capacity is actually running the session, not a lesser
model's.

- **Identify the executing model.** Check your own system context (e.g. "You
  are powered by the model named X") — this is self-knowledge; no shell
  command can answer it.
- **Compare against the declared frontier-window model.** Currently:
  **Fable**, model ID `claude-fable-5`. This is the only line that changes
  when the window moves to a new model; the rest of this skill stays
  model-agnostic.
- **On mismatch: STOP.** Do not proceed to Phase 1 — don't run the survey,
  don't pull the backlog. Tell the user which model is running and which is
  expected, and that they should switch (e.g. `/model fable`) and re-invoke
  fablize. Proceeding on a lesser model is permitted only as an explicit
  user override given after they've been told about the mismatch.
- **On match**, proceed to Phase 1.

## Phase 1 — Survey (autonomous, no approval needed)

1. **Learn what's already spec'd.** Check recent merged history for spec
   work, and read the project's dated-specs directory (`docs/specs/` by
   convention — detect the actual location, or ask, if this project differs)
   to learn the local spec-output pattern. Skip anything already carrying a
   merged spec — those items are usually already in progress.
2. **Collect the backlog.** Invoke the whats-next skill in `all` mode with its
   "show everything" signal — the affordance it documents as `--limit 0` for the
   complete, untruncated list — so candidates aren't selected from a truncated
   backlog, and pull the full open/deferred backlog from the work tracker.
3. **Measure spec coverage.** For each plausible candidate, pull its full
   record and gauge how much description, design rationale, and acceptance
   criteria it already carries. Classify each as **already-spec'd**
   (externalized spec doc, implementation-ready label, rich acceptance
   criteria) or **thin** (one-line description, no design, no AC). Check
   upstream dependency edges too — don't propose spec'ing something a blocked
   dependency makes structurally moot.

   **Then verify each candidate is still real, not just rich.** Coverage
   gauges how *detailed* a bead is; liveness gauges whether the thing it
   describes still exists — a bead can richly specify surfaces that were
   archived or deleted out from under it. For each candidate, extract every
   concrete surface it names (file paths, script names, skill paths, cited
   rule sections) and resolve each against the live tree, **excluding any path
   under `archive/`** (`find … -not -path '*/archive/*'`, or grep for the
   cited text). Match the *cited content*, not just a same-named file: a stub
   can survive at a path while the substance it references was archived, so
   "`foo.md`'s X section" needs that section grepped, not `foo.md`'s mere
   existence. A candidate whose named surfaces are **all** archive-only or
   missing is disqualified from selection — it wants a disposition decision
   (close as superseded, or rescope), not a spec; surface it under Phase 2's
   rejected clusters with that verdict.

   **Read closed siblings' close notes.** A candidate's fate is often settled
   one bead over: a sibling closed as superseded routinely names the exact
   archived surfaces the still-open candidates also depend on — a verdict that
   never propagated to the parent or the open siblings. Before selecting, read
   the `notes`/close text of closed beads under the same parent; a sibling
   note condemning a candidate's surfaces is disqualifying evidence.

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
   | Q3 | Readiness labeling per item — stamp a readiness label at spec merge, or leave labeling to a separate readiness gate (either way, continuation items get minted and the claim gets released at merge — that end-state is not optional; see step 9) |
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
   project's specs directory, following the local pattern, ending with a
   `## Continuations` section that names each follow-on work item to create
   (`- <noun>: <title> — AC: …`) or the literal `- none — this spec is the
   deliverable`. Ship it the same way the environment already ships
   everything else — through its normal completion-gate, worktree, and PR
   discipline; fablize doesn't restate that machinery, only feeds it. At
   spec-PR merge, the delivering session: mints the continuation items in the
   work tracker as children under the still-open objective per the manifest,
   releases the claim on the item (status back to open/unclaimed), and stamps
   phase labels (a readiness label per the Q3 answer).
   Mint-before-anything-closes, always — successors are created before
   anything closes or releases. A work item left claimed behind a merged spec is a defect; a
   readiness label stamped on a still-claimed item is not a deliverable.

## Red Flags

| Rationalization | Reality |
|---|---|
| "The batch could be a bit bigger" | No — human review time is the bottleneck, not model capacity. Default stays 4–6. |
| "This item's spec looks good enough" | Measure description/design/AC content per item; don't eyeball it. |
| "This bead's description is rich, so it's a strong candidate" | Richness isn't liveness. A detailed bead can describe files, scripts, or skills that were archived out from under it. Resolve every named surface against the live tree (excluding `archive/`, matching cited content not just filenames) before selecting; all-archived-or-missing means disqualify and flag for disposition, not spec. |
| "I'll skip the STOP and start spec'ing — the batch is obviously right" | Never. Phase 2 always ends in a stop; approval is not optional. |
| "One strong model can just implement this directly, why spec it" | That defeats the window argument: spec now while frontier capacity is available, implement later on whatever's cheap then. |
| "Mixed-domain batch is fine, they're all just backlog items" | Domain-mixing is the context-switch tax fablize exists to avoid; keep one domain per batch. |
| "The survey phase is mechanical — any model can start it and we can switch later" | Fail fast at entry — batch selection and spec judgment are the point of the window; a mid-flow model switch re-derives context on the expensive model, wasting the budget. |
| "I'll leave the item claimed — implementation comes next anyway" | No. The claim releases at spec merge regardless of what happens next; mint the continuations, release the claim, stamp the labels, in that order. A still-claimed item behind a merged spec is a defect, not a shortcut. |

## NOT For

- Implementing the work itself — fablize only produces specs and
  implementation-ready backlog items.
- Backlog items that already carry an adequate spec — those don't need a
  frontier pass.
- Backlog items whose named surfaces resolve only under `archive/` (or not at
  all) — those describe superseded or removed work; flag them for a
  disposition decision, don't spec them.
- Substituting for the project's own readiness or verification gates —
  fablize feeds those gates, it doesn't replace them.
- Merging pull requests — spec output ships as a PR like anything else;
  fablize doesn't touch merge authority.
