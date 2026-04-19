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

The bead MUST have label `implementation-ready`. One of the following
invocation contexts must apply:

- **`run-queue` in a dedicated session** — autonomous; no per-bead user
  authorization needed (the operator authorized the queue when they
  started it).
- **`start-bead` Route A** for a bead where no
  `implementation-readied-session-<sid-prefix-8>` label matching the
  current session's SID prefix is present (the marker for the current
  session is absent, regardless of whether other session markers exist).
- **In-session override** — user explicitly and affirmatively authorizes
  implementation in the current session (e.g. "implement it now",
  "yes, go"). Completing brainstorming in the same session is NOT
  implicit authorization.

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

Molecules have no structural parent-edge back to the bead (beads `lp3`)
and the tree-mode text path silently drops `--type` / `--parent` filters
(beads `2dx`). Query via the `for-bead-<bead-id>` label convention with
`--json`:

```bash
bd list --label for-bead-<bead-id> --type molecule --json \
  | jq '[.[] | select(.status != "closed")]'
```

Decide from the result array:

- **length 0** → no active molecule. BUT if you suspect a pre-convention
  or otherwise unlabeled molecule exists (prior activity visible in the
  bead's history, user references one), STOP — do NOT pour over
  unlabeled in-progress work. Escalate:
  ```bash
  bd comments add <bead-id> "Probe returned no labeled molecules, but I
    suspect an unlabeled molecule exists because: <reason>."
  bd human <bead-id>
  ```
  Otherwise proceed to Step 3.

- **length 1** → extract and resume (go to Step 4):
  ```bash
  MOL_ID=$(bd list --label for-bead-<bead-id> --type molecule --json \
    | jq -r '[.[] | select(.status != "closed")] | .[0].id')
  bd mol current "$MOL_ID"
  ```
  Do NOT pour a new formula over existing in-progress work.

- **length 2+** → analyze first; don't escalate blindly. Multiple
  non-closed molecules for one bead is legitimate when distinct formulas
  coexist (a lingering brainstorm-bead wisp alongside an
  implement-feature pour) or when parallel agents share the same Dolt
  server. Inspect each:
  ```bash
  bd list --label for-bead-<bead-id> --type molecule --json \
    | jq '[.[] | select(.status != "closed")
               | {id, title, status, updated_at, created_at}]'
  ```
  Resolve if one clearly supersedes the others — an open
  implement-feature/fix-bug pour supersedes a stale brainstorm-bead
  wisp; a more recent pour supersedes an abandoned earlier one. Resume
  the winner (go to Step 4) and tell the user your reasoning; the user
  can burn the loser later.

  If the molecules cannot be cleanly disambiguated, escalate WITH your
  analysis — the human should see your read-out, not a blank flag:
  ```bash
  bd comments add <bead-id> "N active molecules for this bead:
    - <mol-id-1> (<formula>, status=<s>, updated <ts>): <analysis>
    - <mol-id-2> (<formula>, status=<s>, updated <ts>): <analysis>
    Assessment: <duplicative | legacy | needs manual merge>
    Recommended action: <resume X / burn Y / user decides>"
  bd human <bead-id>
  ```
  Do NOT silently pick one.

See `rules/beads.md` ("Molecule → bead linkage convention") for the
stamp procedure applied in Step 3.

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

Note the molecule ID from the output. Immediately stamp the bead→molecule
lookup label so Step 2's existence probe can find this molecule on any
future entry (see `rules/beads.md` "Molecule → bead linkage convention"):

```bash
bd label add <mol-id> for-bead-<bead-id>
```

Then claim the bead and walk the parent chain (see `rules/beads.md` I1):

```bash
bd update <bead-id> --status in_progress

PARENT=$(bd show <bead-id> --json | jq -r '.[0].parent // empty')
while [ -n "$PARENT" ]; do
  bd update "$PARENT" --status in_progress
  PARENT=$(bd show "$PARENT" --json | jq -r '.[0].parent // empty')
done
```

If the bead arrived here via `start-bead` Route A after brainstorming
in a prior session, the brainstorm-bead formula's `claim` step already
set the bead (and ancestors) `in_progress` — re-running `bd update --status in_progress` is a safe no-op. Keep the walk here so the
claim invariant holds no matter which path got us to implementation.

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
| "Brainstorming finished cleanly, so the user must want implementation" | No. Hand off to run-queue by default. Ask or wait for explicit authorization. |
