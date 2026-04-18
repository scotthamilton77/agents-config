---
name: start-bead
description: >
  Use when the user points at a specific bead and wants to start work on it,
  or when routing a bead from create to the right workflow. Evaluates the bead
  and routes to: brainstorm formula (if spec incomplete), implement-bead skill
  (if implementation-ready), or inline execution (if trivial).
---

# start-bead

Evaluate a bead and route it to the right workflow. The traffic cop of the pipeline.

## When to Use

- User says "start on xyz", "let's work on proj-42", "pick up that bug"
- After `bd ready` when the user selects a specific bead to begin
- Programmatically from `run-queue` for implementation-ready beads

## The Process

### Step 1: Read the Bead

```bash
bd show <bead-id>
bd label list <bead-id>
```

Note: type, status, labels, AC, description, dependencies.

### Step 2: Check for Existing Molecule

Before doing anything else, check if a molecule already exists for this bead:
```bash
bd list --parent <bead-id> --type mol 2>/dev/null
bd mol list 2>/dev/null | grep <bead-id>
```

If an active molecule exists → resume it:
```bash
bd mol current <mol-id>
```
Then execute the current step. Do NOT create a new molecule.

### Step 3: Route the Bead

Evaluate the bead against these criteria in order:

---

**ROUTE A: Already implementation-ready**

Condition: has label `implementation-ready`

Action: invoke the `implement-bead` skill directly.

---

**ROUTE B: Trivial — no formula needed**

Condition: ALL of the following are true:
- Change touches ≤ 3 files
- No new tests required
- No worktree needed (too small to warrant isolation)
- No architectural implications
- Completable in a single focused turn

Action: do it inline. No formula, no molecule. Close the bead when done.
If in doubt, it is NOT trivial. Use Route C.

---

**ROUTE C: Needs brainstorming**

Condition: anything that does not meet Route A or B criteria.
This is the default route for feature, task, and chore beads without full specs.

Action: wisp the brainstorm-bead formula:
```bash
bd mol wisp create brainstorm-bead --var bead-id=<id>
```

Then execute the formula as the MAIN AGENT (brainstorming requires
interactive conversation with the user — do NOT dispatch a subagent).

After the formula completes, the bead will have the `implementation-ready`
label and will be picked up by `run-queue`, or the user can invoke
`implement-bead` directly.

---

### Step 4: Report routing decision

Before acting, briefly tell the user what you're doing and why:
> "This bead looks [fully specified / trivial / needs clarification].
>  Routing to [implement-bead / inline / brainstorm formula]."

Exception: if it's obviously trivial, just do it without announcing.

## Routing Decision Table

| Has `implementation-ready` label | Trivial | Route |
|---|---|---|
| Yes | — | implement-bead |
| No | Yes | Inline |
| No | No | Brainstorm formula |

## Red Flags

| Thought | Reality |
|---------|---------|
| "I'll just start implementing, it seems clear enough" | Run the router. Don't shortcut. |
| "The bead has some AC, close enough" | Has `implementation-ready` label? No? Then Route C. |
| "I'll do a quick brainstorm in-line without the formula" | No. The formula provides state tracking and spec review. |
| "This molecule looks incomplete, I'll create a new one" | Resume the existing molecule first. |
