---
name: instructing-subagents
description: Use when writing the prompt for any delegated agent — a subagent, a workflow stage, a background worker, or a nested harness. Apply whenever you are about to hand work to an agent, split a task across agents, or draft a brief, spec, or dispatch for delegated work; and whenever a delegated agent built the wrong thing, returned noise, went idle without delivering its report, or argued with its brief. Dispatching to a restricted-tool subagent such as openrouter-claude-subagent's read-only default needs its mandated report file carved into the tool grant explicitly.
admission:
  prevents: Delegated work that returns noise or loses its result — briefs missing an objective, constraints, acceptance criteria, or a commanded report delivery; briefs that prescribe the orchestrator's implementation instead of the outcome; and finished judgement lost to an agent that went idle holding a good report.
  cost: Context footprint only, bounded by the caps content-lint enforces.
  remove_when: A run of dispatches shows well-formed briefs — criteria, boundaries, delivered reports — written without loading this skill.
---

# Instructing Subagents

A subagent inherits none of your context, your conversation, or your intent. The brief is
the entire interface. Write it as a specification, not a script: define what must be true
when the work is done, and leave how to the agent — once dispatched, it is closer to the
ground truth than you are.

## What a brief carries

Five parts, in this order. Write freely within each; the structure is the contract.

**1. Objective.** The outcome, in a sentence or two: what is true when the agent finishes
that is not true now. If you cannot state this without describing implementation steps,
you have not finished thinking about the task — do that first.

**2. Context.** Only what the agent cannot cheaply discover: the observed symptom and
repro, prior findings, decisions already made and why, pointers to the relevant files or
docs. Give the working root and every file path **absolute** — a relative path lets the
agent anchor on the wrong tree and split its work across two. If you don't know the
agent's working root, tell it to resolve its own and echo the resolved path back.

When the task involves investigation or reasoning, label your own conclusions as claims,
and instruct the agent to be suspicious of them: *treat the assertions in this brief as
hypotheses — confirm or disprove them by your own investigation before building on them.*
An agent that inherits your diagnosis as fact will faithfully extend your mistake.

**3. Constraints and boundaries.** What must still be true when it is done — behaviour
that must not regress, interfaces that must not change. Ownership: which files are the
agent's, what is off-limits, and what to do at the boundary (stop and report, not edit).
Name the verification gate and how to read it: run it standalone and report its exit
status, never inferred from partial output.

**4. Acceptance criteria.** The checks that make "done" mechanical: tests that pass (and
failed first, for a fix), gates that exit zero, artifacts that exist. Criteria are
*conditions*, not steps — "a test reproduces the mangling and passes after the fix," not
"step 4: add a test." An agent given steps performs them; an agent given criteria
verifies them.

**5. Reporting contract.** Say what the report must contain — evidence per criterion,
what was changed or produced, conclusions reached and how they were verified, anything
left undone or uncertain. Then command delivery twice: name a file
path the agent *writes* the report to, and separately instruct — *send this report as
your final message; do not end your turn without it.* A "report back with…" list
describes an artifact and commands no action; agents finish, go idle, and deliver
nothing while holding a good report. Code survives that; judgement does not.

**Fail-fast cases.** Beyond the report on completion, name the task-specific conditions
under which the agent must stop *mid-execution* and come back for clarification or help —
through agent messaging if available, otherwise as a partial report through the same
reporting contract. Enumerate the ones this task can actually hit: the root cause traces
outside its ownership boundary, a needed resource or permission is missing, the next step
is destructive or irreversible, a criterion turns out unreachable as stated, the evidence
contradicts the brief's premise, or the scope is growing past what was dispatched.
Stopping early with a clear question is a success mode; pushing through on a guess is not.

Close every brief with a general stop clause: *if this brief is ambiguous,
self-contradictory, or rests on a premise the evidence does not support, stop and report
rather than guessing — assume there may be an error in my framing.* Briefs that demand
"all suites green" while forbidding the only edit that greens them are the normal case,
not an exotic one.

## Altitude: outcomes, not mechanisms

The dispatcher's most expensive failure is a brief that smuggles in its own wrong theory
of the fix. The boundary: **diagnosis is a noun phrase; mechanism is a verb phrase about
the solution.** State what is true and what must become true, then stop at the verb.

> ✅ "Cache keys are built from endpoint plus params, so two tenants issuing the same
> query collide on one entry. No tenant may read another's; same-tenant caching must
> keep working."
> ❌ "…so add the tenant id to the key."

Even hedged suggestions ("could be a missing `encoding=` on the write") anchor the
investigation on your guess. Put that energy into constraints and criteria instead.
Watch for `add`, `wrap`, `gate`, `move`, `use X here`. The one exception is removal —
prescribe a deletion plainly, and say it is the one place you are prescribing.

## Skeleton

```
Objective: <the outcome — one or two sentences>

Context: <symptom + repro, prior findings, decisions made>
Treat the assertions above as hypotheses — confirm or disprove them by your own
investigation before building on them.
Working root: <absolute path>. All paths below are absolute.

Constraints: <what must not regress; interfaces held stable>
Yours to change: <paths>. Off-limits: <paths> — at the boundary, stop and report.
Gate: run `<gate>` standalone from <root>; report its exit status.

Acceptance criteria:
- <condition, mechanically checkable>
- <condition>

Report: write your report to <absolute path>, covering <contents: evidence per
criterion, what changed or was produced, anything left undone>. Then send the full
report as your final message — do not end your turn without it.

Stop mid-task and come back for guidance — partial report, same path — if:
- <task-specific fail-fast case, e.g. the cause traces outside your boundary>
- <task-specific fail-fast case, e.g. a needed resource or permission is missing>

If any part of this brief is ambiguous, contradicted by what you find, or blocks
its own criteria, stop and report instead of proceeding. Assume there may be an
error in my framing.
```

## Red flags

- An imperative verb about the solution, and the change is not a deletion.
- A brief whose assertions the agent is never told to verify.
- Criteria that read as numbered steps.
- "Report back with…" and no command to send anything.
- A relative path in a brief bound for another working tree.
- An agent went idle and you are about to re-run its work instead of reading its file.
