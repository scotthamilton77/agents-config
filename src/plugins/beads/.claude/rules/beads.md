# Beads

Task tracking workflow (run with `dangerouslyDisableSandbox: true`).

`bd <command> [args]` — Types: bug | feature | task | epic | chore
Priority: 0-4 / P0-P4 (0=critical, 2=medium, 4=backlog). NOT "high"/"medium"/"low".

**Basic workflow**: `bd ready` → pick a bead → `start-bead <id>` → molecule executes → `merge-and-cleanup`

**Rules**:
- Use bd for ALL tracking, `--json` for programmatic use
- No markdown TODO lists unless user explicitly requests
- Discovered work → create bead NOW with `discovered-from:<parent-id>` dep before continuing; don't defer and don't fix inline
- Acceptance criteria: "Build passes. Typecheck passes. Tests pass."
- Epic children parallel by default — only explicit deps create sequence
- For bead-tracked work, specs may be written directly into the bead description (`bd update <id> --description "..."`) — the bead is the plan file
- **`bd create` is pure capture — no claim, no implementation.** Never say "starting work" / "beginning" when the user asks to create/file/capture/track a bead. Reserve "Starting work on task [id]..." strictly for when the user explicitly directs you to START WORK on a specific bead identifier.

**Parent/child workflow** (you forget this):
- Claiming child → mark parent `in_progress` too
- Before work → `bd show <parent-id>` for acceptance criteria and siblings
- Before user review → run completion gate pipeline
- After close → if all siblings closed, close parent recursively

---

## "bd ready" / "what's next" Behavior

When the user runs `bd ready`, asks "what's next", or asks what to work on
**without specifying a direction**, show TWO lists:

**List 1 — Needs your attention:**
```bash
bd human list
```
Escalated items, questions from agents, blockers requiring human judgment.
Show these first. If any exist, address them before looking at the second list.

**List 2 — Ready to brainstorm:**
```bash
bd ready --json | jq '[.[] | select(.labels | index("implementation-ready") | not)]'
```
Beads that are open and unblocked but NOT yet implementation-ready —
these are candidates for a brainstorming session.

Implementation-ready beads are in the `run-queue` pipeline and do
not need manual attention.

When the user says "bd ready" in a **directed context** (e.g. run-queue
is looking for work), use `bd ready --label implementation-ready` instead.

---

## Bead Lifecycle and Labels

Labels track a bead's state through the pipeline:

| Label | Set by | Meaning |
|-------|--------|---------|
| `brainstormed` | brainstorm-bead formula (finalize step) | Spec written and reviewed |
| `implementation-ready` | brainstorm-bead formula (finalize step) | Ready for implement-bead / run-queue |
| `human` | Any agent via `bd human <id>` | Needs human attention |

Label commands:
```bash
bd label add <id> <label>
bd label remove <id> <label>
bd label list <id>
bd ready --label <label>
```

---

## Skill Pipeline

The full bead lifecycle runs through four skills:

1. **`create-bead`** — capture an idea as a placeholder (fast, no spec)
2. **`start-bead`** — route to brainstorm or implement based on readiness
3. **`implement-bead`** — pour formula, orchestrate subagents through DAG
4. **`run-queue`** — autonomous loop: find implementation-ready beads, process them

Plus formulas:
- `brainstorm-bead` — interactive spec writing + RALF spec review → `implementation-ready`
- `implement-feature` — RALF-IT feature implementation
- `fix-bug` — root-cause diagnosis + RALF-IT fix
- `merge-and-cleanup` — retroactive gate + explicit auth → merge

---

## Session Separation

**`run-queue` runs in a dedicated Claude session.**
Do NOT run run-queue in the same session where brainstorming is happening.
The polling loop and background subagents will interrupt interactive conversations.

- Brainstorming session: interactive, user present, no background work
- run-queue session: autonomous, separate window/terminal, no brainstorming

---

## Skill Partnership

Beads and superpowers are partners with distinct roles. Do not confuse them.

- **Beads = OUTER lifecycle** — what work exists, its state, dependencies, and
  multi-session persistence. The bead is the plan. Formulas drive the workflow.
- **Superpowers = INNER methodology** — *how* to actually do the work at each
  step. Skills are invoked *inside* formula steps, not as peers of the bead
  workflow.

### Inner methodology skills (partners — use freely inside formula steps)

- `superpowers:brainstorming`
- `superpowers:systematic-debugging`
- `superpowers:root-cause-tracing`
- `superpowers:test-driven-development`
- `superpowers:verification-before-completion`
- `superpowers:using-git-worktrees`
- `superpowers:finishing-a-development-branch`
- `superpowers:requesting-code-review`
- `superpowers:receiving-code-review`
- `superpowers:dispatching-parallel-agents`

### Off-limits for bead-tracked work (compete with bead lifecycle)

- `superpowers:writing-plans` — the bead description IS the plan
- `superpowers:executing-plans` — `implement-bead` is the executor
- `superpowers:subagent-driven-development` — `implement-bead` orchestrates via the formula DAG

**Rule:** off-limits skills compete with the bead lifecycle. On a bead, use
`start-bead` → `brainstorm-bead` → `implement-bead` instead. Off-limits skills
remain available for non-bead work.
