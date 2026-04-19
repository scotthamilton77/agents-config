---
name: create-bead
description: >
  Use when the user wants to capture an idea, feature, bug, task, chore, or
  enhancement as a tracked work item. Creates a lightweight placeholder bead
  with enough context to be routed later by start-bead. Do NOT brainstorm,
  spec-write, or ask design questions — that is start-bead's job.
---

# create-bead

Capture an idea as a placeholder bead. Fast. No overthinking.

## When to Use

- User says "create a bead for X", "track that", "add that to the backlog"
- After a bug is discovered and needs tracking
- When decomposing an epic into child tasks
- Any time work needs a permanent home before it's ready to implement

**Do NOT use for:** Starting implementation, writing specs, asking design questions.
Those belong in `start-bead` → brainstorm formula.

## The Process

### Step 1: Determine Type and Priority

From context, classify the work:

| Type | When |
|------|------|
| `bug` | Something is broken or behaving incorrectly |
| `feature` | New capability or user-visible behavior |
| `task` | Internal work, refactoring, infrastructure |
| `chore` | Maintenance, cleanup, dependency updates |
| `epic` | Container for a group of related beads |

Priority (if not obvious, default to P2):
- P0: Critical, blocking, prod incident
- P1: High, blocking other work or users
- P2: Normal (default)
- P3: Low, can wait
- P4: Backlog, nice-to-have

### Step 2: Create the Bead

Minimum viable bead — enough to know what it is, not a full spec:

```bash
bd create "<title>" -t <type> -p <priority>
```

For bugs, add reproduction context if available:
```bash
bd create "<title>" -t bug -p <priority> \
  --notes "Repro: <steps>\nActual: <behavior>\nExpected: <behavior>"
```

For child tasks under an epic:
```bash
bd create "<title>" -t task -p <priority> --parent <epic-id>
```

#### Placement of discovered work

When a bead is captured mid-implementation — i.e. you're inside
another in-progress bead and you hit something that needs its own
tracked home — prefer **epic-sibling placement** over the default
orphan-with-`discovered-from`:

```bash
PARENT=$(bd show <current-bead-id> --json | jq -r '.[0].parent // empty')

# If the discovered work is a logical SIBLING SUBTASK of the current
# bead's parent epic, create it INSIDE the epic so it lands with the
# siblings (not as an orphan connected only by a dep link):
if [ -n "$PARENT" ] && <new-work-is-sibling-subtask-of-$PARENT>; then
  bd create "<title>" -t <type> -p <priority> --parent "$PARENT"
else
  # Otherwise create as an orphan and link with discovered-from:
  NEW=$(bd create "<title>" -t <type> -p <priority> --json | jq -r '.id')
  bd dep add "$NEW" <current-bead-id> --type discovered-from
fi
```

**Sibling test** (from `rules/beads.md` I3): would this discovered
work have been on the epic's original plan, if we'd thought of it?
Yes → `--parent <epic-id>`. No (sub-step of the current bead, or only
tangential) → orphan + `discovered-from`.

### Step 3: Add Preliminary Context (if provided)

If the user gave requirements, constraints, or acceptance criteria, add them:
```bash
bd update <id> --acceptance="<preliminary criteria>"
bd update <id> --notes="<any additional context>"
```

If the bead is a dependency of other work:
```bash
bd dep add <other-id> <new-id>   # other-id needs new-id
```

### Step 4: Confirm and Move On

Report back briefly:
> "Created [type] bead `<id>`: <title> (P<n>)"

Do NOT:
- Ask design questions about the feature
- Start fleshing out a spec
- Ask if the user wants to start working on it now
- Add the `implementation-ready` label (that comes from brainstorming)

The bead is a placeholder. Its lifecycle continues with `start-bead`.

## Red Flags

| Thought | Reality |
|---------|---------|
| "I should flesh this out more" | No. Create and move on. |
| "Let me ask a few questions first" | No. Capture what you have. |
| "Should I add implementation-ready?" | No. That comes from brainstorm. |
| "I'll add a bunch of acceptance criteria" | Only if user explicitly provided them. |
