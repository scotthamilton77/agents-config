---
name: orchestrating-subagents
description: Use when orchestrating subagents — dispatching workers, fanning out parallel agents, or any case where a dispatched agent may itself spawn another agent (nested agents). Apply whenever you coordinate multi-agent work, brief a worker that may itself need a sub-step done by another agent, or notice a subagent going idle or silent after launching work it was waiting on.
---

# Orchestrating Subagents

## Overview

A subagent **cannot await or be notified of a child agent it spawns** — this is a runtime
fact, not a style choice. When a worker spawns its own subagent for a sub-step and then
"waits," it ends its turn and idles silently until the root orchestrator re-engages it.

This skill is for the agent doing the orchestrating (the root session, or any agent that
dispatches others). It gives you the constraint, a decision ladder that avoids the trap, and —
when nesting is truly unavoidable — a file-relay handoff that coordinates parent, child, and
orchestrator without bloating anyone's context.

## When to use

- You are dispatching one or more subagents to do work.
- A worker you dispatch will itself need a sub-step that another agent would perform.
- A subagent has gone idle or silent shortly after it launched other work.
- You are designing any kind of workflow that could run agents inside agents.

**Not for:** single-shot dispatch where the child does everything and returns — just dispatch
and read the result.

## The constraint (mechanical — not negotiable)

The orchestrator MUST always spawn named agents (teammates).
- A **named** teammate cannot spawn a **named** child (flat roster) — nested children must be
  unnamed subagents.

When agent A spawns child B with the Agent tool:

- The Agent tool returns an **async handle only** ("Async agent launched…"), never B's result
  inline — and it instructs A to "end your response."
- **B's completion notification routes to the ROOT orchestrator, not to A.** A is suspended;
  it is resumable but never self-wakes.
- A has **no way to block on B**: `TaskOutput` (block-retrieve) is absent from a subagent's
  toolset (root-only); `TaskGet`/`TaskList` cannot even see B's task; foreground `sleep`/waits
  are disabled; a `run_in_background`/`Monitor` watcher A arms does **not** re-invoke A when it
  fires.

So: **never brief a worker to "spawn an agent and wait for it."** It will stall.

## Decision ladder — prefer not to nest

Take the highest rung that fits. Each rung down adds coordination cost and stall risk.

1. **Worker spawns nothing — it does the whole job itself.** When you know the worker's entire
   workflow can be completed without a separate agent, brief it to spawn **no** subagents and do
   every step inline — its own reasoning, its own tool calls, its own synchronous scripts. A
   worker has no children to deadlock on, so it cannot stall. Most reliable; the default.
2. **Worker offloads deterministic sub-steps to synchronous scripts.** A subagent CAN block on a
   blocking Bash call within a single turn — it just cannot await a child *agent*. Push
   lint/build/test/format/status-poll work into a script the worker runs and waits on inline.
   Still zero agent-nesting.
3. **Orchestrator owns the agent sub-step.** When a sub-step genuinely needs a *separate agent*
   (fresh context, a different model, parallel fan-out), don't make the worker spawn it. The
   worker reports DONE and stops; YOU (root) run that agent as your own child — its completion
   wakes you correctly — then re-engage the worker only if there's follow-up.  If this is 
   impractical because only the worker will have the context to properly brief the sub-step,
   proceed to rung 4.
4. **File-relay handoff** (below). Only when the agent sub-step must run *mid-worker* and the
   worker must keep going afterward — i.e., it cannot simply report DONE and stop.

## The file-relay handoff contract

Brief worker A with ALL of this when it must spawn child B for step Y and then continue to Z:

1. **B writes, returns a filename.** B writes its outcome **atomically** (write temp → `mv`)
   to a unique `/tmp` path (derive uniqueness from B's `agentId`), first line `STATUS: OK|FAIL`,
   and returns **only the filename** as its final message — never the payload.
2. **A hands off, then ends its turn.** Before ending, A `SendMessage`s the orchestrator:
   `HANDOFF: child_agentId=<id>, output_path=<path>, parked at Y`. Then A ends its turn.
3. **Orchestrator relays the locator only.** On B's completion, the orchestrator correlates by
   `agentId` (it equals the completion task-id) and `SendMessage`s A: "child done — see
   `<path>`." The orchestrator does **not** read the file; relaying a path keeps it lean.
4. **A resumes and reads it itself.** A reads `<path>`, checks `STATUS: OK`, continues to Z. On
   missing/`FAIL`, A escalates to the orchestrator.

The payload flows **B → disk → A**, bypassing the orchestrator. The orchestrator holds only
three short strings per parked worker: name, child `agentId`, path.

## Orchestrator duties when running nested workers

- **Expect the bare idle, and do nothing with it.** A parked worker emits no content on its own —
  only a handoff if you briefed it to send one. An idle therefore means *parked*: not "done," not
  "stuck," not "waiting on you."
- **A bare idle is not an event — it is the absence of one.** Never let an idle *itself* trigger
  anything: do not reply to it, do not `SendMessage` the parked worker about it, do not log or
  narrate it. Idles are the most frequent notification in a nested run and carry the least
  information; treating each one as a prompt spends the orchestrator's context on the news that
  nothing happened. Act on **real** signals — a child's completion notification, a handoff, a
  report, a watcher ring. The orchestrator *does* re-engage a parked worker, but because a child
  completed, never because the parent went quiet.
- **The idle is not a trigger — but silence that outlasts the work is.** Ignoring idles is not
  ignoring workers. When a worker has been quiet materially longer than its task should take, that
  overdue-ness is a real signal and you act on it. The distinction is what you key on: an idle is a
  turn boundary a *healthy* worker emits, while a crashed one may emit nothing at all — so the idle
  is the one channel a dead worker has stopped using. Detect death by elapsed time against a missing
  artifact, never by counting idles.
- **Probe the world, not the worker.** On an overdue worker, do NOT `SendMessage` it to ask. A
  message to an already-terminated agent silently no-ops or raises an error that reads like a
  successful dispatch, so a ping cannot tell "dead" from "parked and quiet" — and a live worker's
  answer is a claim anyway. Check its status through the harness, and read the artifact it was to
  produce (git/gh/bd, the relay file at its handoff path). Missing artifact plus a terminated status
  is a crash: re-dispatch the work. Missing artifact plus a live agent is slow, not dead — leave it
  alone.
- **Verify ground truth before resuming.** A worker's narration is a claim, not a fact — read
  git/gh/bd to learn the true state, then re-engage precisely.
- **A child's completion arriving to YOU means the parent did not see it** — that is your cue to
  relay and resume the parent.

## Common mistakes

| Mistake | Consequence | Fix |
|---|---|---|
| Brief a worker to spawn an agent when it could do the job inline | Needless nesting + stall risk | Rung 1: brief it to spawn nothing |
| Reply to, or log, a bare idle notification | Context burned narrating that nothing happened; real signals buried | Treat the idle as silence; act only on completions, handoffs, and reports |
| Brief a worker to "spawn an agent and wait" | Stalls forever | Rung 3, or the handoff |
| Worker arms `run_in_background`/`Monitor` to await its child | Never re-invoked; still stalls | Hand off and end the turn, or rung 1/2 |
| Child returns its full payload | Orchestrator context bloats on relay | Child returns only the filename |
| Orchestrator reads the relay file to forward its contents | Orchestrator context bloats | Relay the path only; the worker reads it |
| Treat a worker's silent idle as "done" | Half-finished work shipped | Verify git/gh/bd first |
| Spawn a named child from a named teammate | Rejected (flat roster) | Spawn the child unnamed |
