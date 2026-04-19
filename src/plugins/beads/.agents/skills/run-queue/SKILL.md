---
name: run-queue
description: >
  Use when the user says "start implementing beads", "process the queue",
  "work through the backlog", or similar. Autonomously finds implementation-ready
  beads and executes them one by one using the implement-bead skill with subagents.
  Runs in a dedicated session — do NOT mix with brainstorming sessions.
---

# run-queue

Autonomous implementation queue processor. Find ready beads. Execute them.
Repeat. You are the orchestra conductor; subagents play the instruments.

## When to Use

- User says "start implementing beads" / "process the queue" / "work the backlog"
- There are implementation-ready beads and you want to process them without
  manually invoking implement-bead for each one

## Session Isolation — IMPORTANT

**This skill runs in a dedicated Claude session.**
Do NOT run this skill in the same session where the user is brainstorming.
The background polling and subagent dispatches will interrupt the conversation.

If the user asks you to run the queue while you're in an active brainstorm
or planning discussion:
> "I should run the queue in a separate session to avoid interrupting our
>  conversation. Open a new Claude Code window and say 'start implementing
>  beads' there."

## The Process

### Step 1: Initial Check

Before starting the polling loop, do one immediate check for ready beads:

```bash
bd ready --label implementation-ready --json
```

If beads found: start processing immediately (skip to Step 3).
If none found: start the polling loop (Step 2).

Also check for any pending human escalations before starting:
```bash
bd human list
```
If escalations exist: report them to the user and ask if they should be
addressed first, or if you should proceed with the queue.

### Step 2: Poll for Ready Beads

Launch the polling script as a background process:

```bash
Bash(
  command: "${CLAUDE_SKILL_DIR}/poll-ready-beads.sh [max-minutes]",
  run_in_background: true
)
```

Pass `max-minutes` if the user specified a time limit (e.g., "run for 2 hours").
Omit for indefinite polling.

Announce to the user:
> "Queue is currently empty. Polling every 10 minutes for new
>  implementation-ready beads. I'll notify you when work arrives.
>  [If max given: Will stop after N minutes if nothing shows up.]"

When the script completes (exit 0): proceed to Step 3 with the bead JSON.
When the script exits 1 (timeout): report to the user and stop.
When the script exits 2 (interrupted): report and stop.

### Step 3: Process a Bead

Take the first bead from the ready list:
```bash
BEAD_ID=$(echo "$RESULT" | jq -r '.[0].id')
```

Report:
> "Processing bead `<id>`: <title>"

Invoke the `implement-bead` skill for this bead.

**The main agent orchestrates; subagents implement.** While implement-bead
is running its orchestration loop (dispatching subagents), the main agent
tracks progress and surfaces any `bd human` escalations.

### Step 4: After Bead Completes

When the implement-bead orchestration loop finishes for this bead:

1. Check for human escalations:
   ```bash
   bd human list
   ```
   If any: surface to user, pause until addressed.

2. Report completion:
   > "✓ Completed bead `<id>`: <title>. PR #N awaiting review."

3. Go back to Step 1 (check for the next ready bead).

### Step 5: Queue Drains

When Step 1 finds no ready beads after completing a bead, start a new
polling cycle (Step 2) to wait for more.

The loop continues until:
- The user interrupts
- The polling script times out (if max-minutes was set)
- The user says "stop" or closes the session

## Handling Human Escalations

At any step transition, check:
```bash
bd human list --json
```

If new escalations exist since last check:
- Pause the queue
- Present the escalated items to the user
- Wait for the user to respond/dismiss each one:
  ```bash
  bd human respond <id>   # after getting user's response
  bd human dismiss <id>   # if user says ignore it
  ```
- Resume the queue after escalations are cleared

## Parallel Bead Execution

By default, process one bead at a time (sequential). This is simpler and
avoids git conflicts between concurrent implementations.

**Do NOT parallelize** unless the user explicitly requests it and the beads
are confirmed to touch completely separate parts of the codebase.

## Summary Reporting

After each bead completes, maintain a running tally:
```
Queue Progress:
  ✓ proj-42: Add rate limiting (PR #17)
  ✓ proj-38: Fix auth token expiry (PR #18)
  → proj-45: Refactor session store (in progress...)
```

When the queue drains, present the full summary.

## Red Flags

| Thought | Reality |
|---------|---------|
| "I'll do the implementation myself" | No. Dispatch subagents via implement-bead. |
| "I'll brainstorm this quick spec gap while processing" | No. Stop queue, tell user, separate session. |
| "The user said 'ok', I'll merge this PR" | No. Merging needs explicit authorization. Never in run-queue. |
| "This bead isn't fully ready, I'll spec it quickly" | No. Only `implementation-ready` beads belong here. |
| "I'll process two beads at once for speed" | No. Sequential unless explicitly asked. |
| "The bead isn't quite implementation-ready, I'll brainstorm the gap inline" | No. run-queue processes implementation-ready beads only. If the spec has gaps, flag the bead for re-brainstorming and move on. |
