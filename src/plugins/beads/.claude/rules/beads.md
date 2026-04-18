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
