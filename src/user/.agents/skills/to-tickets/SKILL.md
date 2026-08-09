---
name: to-tickets
description: Break a settled plan, spec, or the current conversation into build slices — tracer-bullet vertical tickets on the tracker, each sized to one context window and declaring the tickets that block it. Use when the decisions are already made and the work needs slicing, sequencing and publishing. Not for scoping open questions — a ticket here is resolved by shipping it, not by answering it.
disable-model-invocation: true
admission:
  provides: A published set of vertical slices with real blocking edges on the tracker, each independently demoable and sized to one context window, from a spec or conversation that states an outcome and no sequence.
  cost: Per invocation, a decomposition pass, one round of approval with the user, and two tracker passes — mint, then wire.
  remove_when: The executor slices a spec into independently mergeable work and wires its dependency edges itself, so nothing invokes this.
---

<!--
Source: skills/engineering/to-tickets/
Upstream: https://github.com/mattpocock/skills @ 84fdeffd12f2ee307994d1eb6feb48173b6e0502
Last sync: 2026-08-07
Drift policy: local-fork — local ticket store and triage label removed, publishing rewritten onto work verbs, ticket body reduced to what the facade carries no field for; do not re-sync
-->

# To Tickets

Break a plan, spec, or conversation into **tickets** — tracer-bullet vertical slices, each declaring the tickets that **block** it.

This is the step after the decisions are made. If what is in front of you is still a set of open questions rather than a set of things to build, this is the wrong skill: scope it first, and come back when there is a route to slice.

## Process

### 1. Gather context

Work from whatever is already in the conversation context. If the user passes a reference (a spec path, a work item id) as an argument, fetch it and read its full body and notes.

### 2. Explore the codebase (optional)

If you have not already explored the codebase, do so to understand the current state of the code. Ticket titles and descriptions should use the project's domain glossary vocabulary, and respect ADRs in the area you're touching.

Look for opportunities to prefactor the code to make the implementation easier. "Make the change easy, then make the easy change."

### 3. Draft vertical slices

Break the work into **tracer bullet** tickets.

<vertical-slice-rules>

- Each slice cuts a narrow but COMPLETE path through every layer (schema, API, UI, tests) — vertical, NOT a horizontal slice of one layer
- A completed slice is demoable or verifiable on its own
- Each slice is sized to fit in a single fresh context window
- Any prefactoring should be done first

</vertical-slice-rules>

Give each ticket its **blocking edges** — the other tickets that must complete before it can start. A ticket with no blockers can start immediately.

**Wide refactors are the exception to vertical slicing.** A **wide refactor** is one mechanical change — rename a column, retype a shared symbol — whose **blast radius** fans across the whole codebase, so a single edit breaks thousands of call sites at once and no vertical slice can land green. Don't force it into a tracer bullet; sequence it as **expand–contract**. First expand: add the new form beside the old so nothing breaks. Then migrate the call sites over in batches sized by blast radius (per package, per directory), each batch its own ticket blocked by the expand, keeping CI green batch to batch because the old form still exists. Finally contract: delete the old form once no caller remains, in a ticket blocked by every migrate batch. When even the batches can't stay green alone, keep the sequence but let them share an integration branch that all block a final integrate-and-verify ticket — green is promised only there.

### 4. Quiz the user

Present the proposed breakdown as a numbered list. For each ticket, show:

- **Title**: short descriptive name
- **Blocked by**: which other tickets (if any) must complete first
- **What it delivers**: the end-to-end behaviour this ticket makes work

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the blocking edges correct — does each ticket only depend on tickets that genuinely gate it?
- Should any tickets be merged or split further?

Iterate until the user approves the breakdown.

### 5. Publish through the `work` facade

`work` is the tracker, and it needs no setup step. A ticket that is not on the tracker is not a ticket — never write a parallel set of ticket files beside a tracker that exists. If `work` is not installed, or the project has no tracker at all, publish the numbered breakdown from Step 4 as a single markdown file instead — one heading per ticket, blocking edges as a list — and say so in the handoff.

Publish in **two passes**, because a blocking edge needs both ids to exist before it can be drawn.

**Pass one — mint the tickets**, in dependency order (blockers first):

```
work create <noun> --title "<title>" --parent <container-id> \
  --description "<what to build>" --acceptance "<criteria>"
```

- `<noun>` is `feat` for new behaviour, `bugfix` for a defect, `chore` for mechanical work.
- `--parent` is the container this effort already has — the spec or epic the slices belong to. If there is none, mint one first (`work create epic --title "<the effort>" --orphan`) and hang the slices off it. Scattering slices as orphans loses the set.
- If the facade refuses the create for want of a track, it names the tracks the project has configured; pick one and pass `--track`. Slices minted under a tracked parent inherit its track and need no flag.
- Record each id the facade returns — pass two needs them.

**Pass two — wire the blocking edges:**

```
work dep add <blocked-ticket> <blocking-ticket>
```

Read it as "the first depends on the second". One call per edge.

Do NOT close or modify the container or any parent item — it holds the rest of the effort's slices, and closing it drops every one of them out of the ticket frontier.

### 6. Hand off the ticket frontier

`work ready` now returns the **ticket frontier** — every ticket whose blockers are all closed and which nobody has claimed. This frontier is work that is startable, not questions that are answerable. For a purely linear chain it is top to bottom. Whoever picks one up takes it with `work claim <id>` first, so concurrent sessions don't collide.

## What goes in the ticket body

The facade carries most of the structure as fields, so the body only holds what has nowhere else to go:

- The **parent** is the `--parent` edge, not a section of prose.
- The **blocking edges** are `work dep` edges, not a "Blocked by" list.
- The **acceptance criteria** are `--acceptance`, one criterion per line.

That leaves `--description` to carry one thing: **the end-to-end behaviour this ticket makes work, from the user's perspective** — not a layer-by-layer implementation list.

Avoid specific file paths or code snippets — they go stale fast. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it and note briefly that it came from a prototype. Trim to the decision-rich parts — not a working demo, just the important bits.
