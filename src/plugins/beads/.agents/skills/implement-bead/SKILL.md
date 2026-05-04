---
name: implement-bead
description: >
  Use when a bead has the implementation-ready label and is ready for
  autonomous execution. Drives ONE stage of the bead's molecule and exits.
  Invoked by the shell driver via `claude -p /implement-bead <bead-id>`.
  The invoking agent is the ORCHESTRATOR only — all implementation work
  is done by subagents. Do NOT invoke this skill for beads that have not
  been through brainstorming (use start-bead to route correctly).
model: sonnet[1m]
effort: high
---

# implement-bead

Drive ONE stage of the bead's molecule DAG and exit. The shell driver
(`scripts/bead-driver-test.sh`) calls this skill once per ready stage via
`claude -p --session-id <uuidv5> "/implement-bead <bead-id>"`. This skill
reads the current step, executes it, closes the step, and exits. The shell
driver handles looping — this skill MUST NOT loop to the next step.

## When to Use

- Invoked by the shell driver via `claude -p /implement-bead <bead-id>`
- The bead MUST have label `implementation-ready`
- Do NOT invoke directly for beads that lack `implementation-ready` — use `start-bead`
- Do NOT invoke in the same session where brainstorming is happening (session separation rule)

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
  bd comments add <bead-id> "Probe returned no labeled molecules, but I suspect an unlabeled molecule exists because: <reason>."
  bd label add <bead-id> human
  ```
  Otherwise proceed to Step 3 to pour a new molecule.

- **length 1** → extract and go directly to Step 4 (find the current step):
  ```bash
  MOL_ID=$(bd list --label for-bead-<bead-id> --type molecule --json \
    | jq -r '[.[] | select(.status != "closed")] | .[0].id')
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
  Resolve if one clearly supersedes the others. Resume the winner (go to
  Step 4) and record your reasoning. The user can burn the loser later.

  If molecules cannot be cleanly disambiguated, escalate WITH your analysis:
  ```bash
  bd comments add <bead-id> "N active molecules for this bead: ..."
  bd label add <bead-id> human
  ```
  Do NOT silently pick one.

See `rules/beads.md` ("Molecule → bead linkage convention") for the
stamp procedure applied in Step 3.

### Step 3: Pour the Formula (only if no active molecule from Step 2)

Select formula based on bead type:
- `bug` → `fix-bug`
- `feature`, `task`, `chore` → `implement-feature`

**Pour vs. wisp:** Default to pour (persistent across sessions). Wisp only
if the bead is trivially small AND single-session completion is certain.

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
lookup label (see `rules/beads.md` "Molecule → bead linkage convention"):

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

### Step 4: Find the ONE Current Ready Step

Query the molecule for its current step using `--json` (text-mode is
unreliable — see beads bug `2dx`):

```bash
bd mol current <mol-id> --json
```

If no current step is returned (molecule is complete or all steps closed),
EXIT immediately. The shell driver will handle close-walk and cleanup.
Do NOT squash or burn the molecule here — that is the driver's job.

Extract the step bead ID from the result.

### Step 5: Execute the Step

Read the step bead's full description:

```bash
bd show <step-bead-id>
```

Execute the instructions in that step bead. Dispatch subagents as needed
per the step description. The step description is self-contained — the
molecule's DAG enforces sequencing; you do not need to explain prior steps
to each new subagent.

**Subagent dispatch instructions** — for each step, pass:
1. The full text of the step bead description (from `bd show <step-bead-id>`)
2. The original bead context: title, AC, and bead ID
3. The cwd contract for this stage (decoded from the molecule's `worktree-path-*`
   label for most stages; repo root for `preflight` and `merge-or-handoff`)
4. The instruction: "Execute this step completely. Report back what you did."

**Subagent isolation**: each subagent is independent and has no context
from previous subagents. The step bead description must be self-contained.

### Step 6: Close the Step and EXIT

When the step is complete, close the step bead:

```bash
bd close <step-bead-id> --reason "<brief summary of what was done>"
```

Then EXIT. Do NOT loop to the next step. Do NOT call `bd mol current` again.
The shell driver polls for the next ready step and spawns a new `claude -p`
invocation for each subsequent stage.

## Important Constraints

**This agent orchestrates. Subagents implement.**
The main agent MUST NOT:
- Write implementation code
- Run tests directly
- Create PRs
- Push branches
- Make git commits

All of these happen inside subagents executing the molecule step bead's instructions.

**One step per invocation.** This skill is called once per stage by the
shell driver. Driving multiple steps in a single invocation defeats the
per-stage context-bounding and session-id resumption model.

**No unauthorized merges.**
The implement-feature and fix-bug formulas end at `review-cycle`.
They do NOT merge. Merging requires explicit user authorization and is
handled separately via the `merge-and-cleanup` formula.

**Discovered work:**
If a subagent reports discovered work, create new beads immediately.
Do NOT add them to the current molecule or fix them inline.

## Red Flags

| Thought | Reality |
|---------|---------|
| "I'll loop to the next step before exiting" | No. One step per invocation. Exit after closing the step. The shell driver loops. |
| "I'll invoke `ralf-it` / `superpowers:subagent-driven-development` directly" | No. Those methodology skills run INSIDE molecule steps, not as peers. |
| "The step is small — I'll skip the subagent and do it in the main agent" | No. Main agent orchestrates, subagents implement. Dispatch even for small steps. |
| "I'll skip the formula and just run the work directly" | The formula IS the workflow. Skipping it skips the gate. |
| "Brainstorming finished cleanly, so the user must want implementation" | No. Hand off to run-queue / shell driver by default. |
