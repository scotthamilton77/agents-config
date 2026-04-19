---
name: implement-bead
description: >
  Use when a bead has the implementation-ready label and is ready for
  autonomous execution. Pours the appropriate formula, then orchestrates
  subagents through the molecule DAG step by step. The invoking agent is
  the ORCHESTRATOR only — all implementation work is done by subagents.
  Do NOT invoke this skill for beads that have not been through brainstorming
  (use start-bead to route correctly).
---

# implement-bead

Pour a formula and orchestrate subagents through the resulting molecule DAG.
The main agent manages; subagents build.

## When to Use

- Bead has label `implementation-ready`
- Invoked by `start-bead` after routing, or by `run-queue` autonomously
- User explicitly says "implement bead xyz" after brainstorming is complete

**Do NOT use when:** bead lacks `implementation-ready` label — use `start-bead`.

## The Process

### Step 1: Read the Bead

```bash
bd show <bead-id>
bd label list <bead-id>
```

Confirm `implementation-ready` label is present. If absent, stop and invoke
`start-bead` instead.

### Step 2: Check for Existing Molecule

```bash
bd list --parent <bead-id> --type mol 2>/dev/null
```

If an active molecule exists for this bead: resume it (go to Step 4).
Do NOT pour a new formula over existing in-progress work.

### Step 3: Pour the Formula

Select formula based on bead type:
- `bug` → `fix-bug`
- `feature`, `task`, `chore` → `implement-feature`

Select pour vs. wisp:
- **Pour** (default): work may span multiple sessions or is non-trivial
- **Wisp**: only if the work is clearly completable in this single session
  AND the user explicitly indicated so

```bash
# Default (pour — persistent across sessions)
bd mol pour implement-feature \
  --var feature="<bead title>" \
  --var bead-id=<bead-id>

# Or for bugs:
bd mol pour fix-bug \
  --var bug="<bead title>" \
  --var bead-id=<bead-id>
```

Note the molecule ID from the output. Mark the bead in_progress:
```bash
bd update <bead-id> --status in_progress
```
If the bead has a parent, mark that in_progress too.

### Step 4: Orchestration Loop

Execute each molecule step by dispatching subagents. The main agent
ONLY orchestrates — it does not write code, run tests, or create PRs.

```
LOOP:
  1. next_step = bd mol current <mol-id> --json
  2. if no next step (molecule complete): exit loop
  3. step_desc = bd show <step-bead-id>
  4. dispatch subagent with step instructions (see below)
  5. wait for subagent to complete and close step bead
  6. report: "✓ <step title>" to user
  7. check for bd human escalations: bd human list --json
     if any new: surface to user and pause loop
  8. go to 1
```

**Subagent dispatch instructions** — for each step, pass:
1. The full text of the step bead description (from `bd show <step-bead-id>`)
2. The original bead context: title, AC, and bead ID
3. The instruction: "Execute this step completely. When done, close the step
   bead with `bd close <step-bead-id> --reason '<brief summary>'`.
   Report back what you did."

**Subagent isolation**: each subagent is independent and has no context
from previous subagents. The step bead description must be self-contained.
The molecule's DAG enforces sequencing — you do not need to re-explain
previous steps to each new subagent.

### Step 5: Molecule Complete

When `bd mol current` returns no more steps:

```bash
bd mol squash <mol-id>   # compress to digest (pour)
# or:
bd mol burn <mol-id>     # discard (wisp)
```

Report to the user:
> "Molecule complete for <bead-id>. PR created and awaiting review.
>  Authorize merge when ready with: 'go ahead and merge PR #N'"

## Pour vs. Wisp Decision Guide

| Signal | Pour | Wisp |
|--------|------|------|
| Work may span sessions | ✓ | |
| Complex feature, many steps | ✓ | |
| User didn't specify | ✓ | |
| "Quick", "small", "one-shot" in bead title | | ✓ |
| User says "do it in this session" | | ✓ |
| Trivial bug with obvious fix | | ✓ |

**Default: Pour.** When in doubt, pour. A poured molecule that finishes in
one session is fine. A wisped molecule that needs a second session is lost.

## Important Constraints

**This agent orchestrates. Subagents implement.**
The main agent MUST NOT:
- Write implementation code
- Run tests directly
- Create PRs
- Push branches
- Make git commits

All of these happen inside subagents executing molecule step beads (the runtime instances of the formula's step definitions).

**No unauthorized merges.**
The implement-feature and fix-bug formulas end at `await-review`.
They do NOT merge. Merging requires explicit user authorization
and is handled separately via the `merge-and-cleanup` formula.

**Discovered work:**
If a subagent reports discovered work, create new beads immediately.
Do NOT add them to the current molecule or fix them inline.

## Red Flags

| Thought | Reality |
|---------|---------|
| "I'll just invoke `ralf-it` / `superpowers:subagent-driven-development` / `superpowers:executing-plans` directly" | No. `implement-bead` pours a formula; those methodology skills run INSIDE molecule steps, not as peers. |
| "The step is small — I'll skip the subagent and do it in the main agent" | No. Main agent orchestrates, subagents implement. Dispatch even for small steps. |
| "I'll skip the formula and just run the work directly" | The formula IS the workflow. Skipping it skips the gate. |
