# Writing the Description (The Pushy-vs-Workflow Synthesis)

The description does TWO jobs that look contradictory but aren't:

1. It must **make the agent load the skill body when relevant.** Agents
   undertrigger — they skip useful skills because the description didn't
   ring loud enough. Be aggressive about listing trigger contexts.
2. It must **NOT short-circuit the agent into acting on the description
   alone.** When a description summarizes the workflow, agents follow the
   description and skip the body — even when the body contains critical
   detail the description couldn't fit.

These reconcile cleanly: **be pushy about WHEN, never about WHAT or HOW.**

A description can be trigger-dense AND process-free at the same time. The
two failures it must avoid are independent — undertriggering is solved by
listing more contexts; body-skipping is solved by removing all process
description. You can do both.

## Examples

```yaml
# ❌ BAD — summarizes workflow, agent will follow this instead of reading the body
description: Use when executing plans — dispatches subagent per task with code review between tasks

# ❌ BAD — too much process detail
description: Use for TDD — write test first, watch it fail, write minimal code, refactor

# ❌ BAD — too narrow, agent won't load skill in obvious adjacent cases
description: Use when writing unit tests in Python

# ❌ BAD — abstract, no concrete triggers
description: For async testing

# ✅ GOOD — trigger-dense, pushy, process-free
description: Use when tests have race conditions, timing dependencies, or pass/fail inconsistently. Apply whenever the user mentions flakiness, hangs, timeouts, zombie processes, or "works locally but fails in CI" — even if they describe the symptom without naming async/timing as the cause.

# ✅ GOOD — pushy on triggers, no workflow
description: Use when executing implementation plans with independent tasks in the current session. Apply whenever the user references a plan file, a checklist of work, or a series of steps to carry out, even if they don't explicitly call it a "plan."
```

## Be pushy by

- Listing every distinct **branch** — a case the skill handles differently.
  One trigger per branch; two spellings of one branch are that branch written twice.
- Naming adjacent symptoms that are their own branch ("flaky," "hangs,"
  "zombie process," "works locally but fails in CI") — the situations a user
  lands in, not restatements of one situation.
- Including cases where the user doesn't name the skill or its concepts.

## Be process-free by

- No verbs that describe the skill's internal steps ("dispatches," "reviews,"
  "runs," "iterates").
- No mentions of subagents, scripts, or tools the skill uses internally.
- No numbered phases or "first ... then ..." constructs.

## Keyword coverage

Name the situations an agent would recognise — error messages, symptoms, tool
names. "Hook timed out," "ENOTEMPTY," "race condition," "flaky," "pollution,"
"teardown." Those are distinct symptoms; three spellings of one of them are not.

## Naming

Verb-first, active voice. `creating-skills` beats `skill-creation`.
`condition-based-waiting` beats `async-test-helpers`. Gerunds (`-ing`) work
well for processes.
