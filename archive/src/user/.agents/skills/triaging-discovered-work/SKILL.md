---
name: triaging-discovered-work
description: Use when a task, test, review, or implementation reveals new work requiring a scope, filing, or deferral decision, including bugs, missing requirements, scope expansions, and mid-task follow-ups that could be incorrectly filed, orphaned, or deferred.
model: sonnet
---

# Triaging Discovered Work

The always-loaded discovered-work rule is the tripwire. This skill owns the
filing-time contract. A discovered item must be fixed now or leave a complete,
anchored, and auditable record.

## Iron Law

**NO FILING OR DEFERMENT WITHOUT SCOPE ADJUDICATION.**

Schedule pressure, a nearly complete PR, or a request to “just create a work item” do
not create an exception. A discovery is not a deferral channel for work already
in scope.

## Decide the Scope

Apply the sibling test: *would this have been on the current work item's
original plan or spec?*

### In scope: fix it in this session

Do the work in the current session and PR. Deferral is permitted only when one
of these escape hatches applies:

- **externally-blocked** — credentials, an upstream fix, or another PR must land first;
- **blast-radius** — the fix enters a subsystem or risk class outside this change; or
- **own-cycle** — the work needs its own design, tests, and review and would roughly double the diff.

Every in-scope deferral requires all of the following:

1. Create it as a sibling of the in-flight work item: `bd create --parent <parent-of-in-flight-bead>`.
2. Add the triage block with `Scope: in-scope — deferred: <hatch> — <why>`.
3. Add an escalation line under **Remaining Work** in the completion report.
4. Do not close the newly filed work item in this session.

If the in-flight work item has no parent, use the out-of-scope anchoring procedure
and record session or PR provenance in the triage block.

### Out of scope: file it anchored

1. Find the best-fit epic beneath the milestone the work maps to. If no epic
   fits, use the milestone itself.
2. Create the work item under that anchor: `bd create --parent <anchor-id>`.
3. Add provenance as well as placement: `bd dep add <new-id> <current-work-id> --type discovered-from`.
4. Append the triage block.

Parentage is placement; `discovered-from` is provenance. Keep both edges.

An orphan is allowed only when no milestone fits. Escalate it in the completion
report as `unanchored — needs your call`; do not quietly file and forget it.

## Required Triage Block

Append this to every filed discovered-work work item:

```markdown
## Triage
- Scope: out-of-scope — <one line why>
- Priority: P<N> — <one line why>
- Anchor: <epic-or-milestone-id> — <one line why>
```

For an in-scope deferral, replace the Scope value with
`in-scope — deferred: <hatch> — <why>`.

## Preserve Close-Walk Safety

Never file a discovery as a child of the in-flight work item itself. Do not close a
newly filed discovery or, for an out-of-scope item, its new anchor chain in the
current session. Closing the last structural child can auto-close its parent
while the in-flight work is still pending. If this happens, recover with
`bd reopen <parent>` and audit the propagated close-walk before continuing.

## Completion Reporting

Use `verify-checklist` for the canonical completion manifest and triage audit.
Follow its reporting contract for every discovery and every in-scope deferral.

## Worked Example

An in-scope validation gap would roughly double the current diff. It qualifies
for `own-cycle`, so create a sibling under the current work item's parent, record
`Scope: in-scope — deferred: own-cycle — requires its own design and tests`,
set a priority with rationale, leave the new work item open, and add a Remaining Work
escalation. Do not create it under the in-flight work item or close it before the
session ends.

## Rationalizations

| Excuse | Reality |
|---|---|
| “The PR is nearly done; I can file it later.” | If it is in scope, fix it now unless a named escape hatch applies. |
| “A provenance edge is enough.” | Provenance is not placement; file under a roadmap anchor too. |
| “It has no matching epic, so an orphan is fine.” | Use the milestone when possible; an orphan is a loud human escalation. |
| “I can close the new work item so the board stays tidy.” | Closing it can close the in-flight parent through close-walk. |

## Red Flags — STOP

- “Just make a work item.”
- “We can decide the anchor later.”
- “This was in scope, but it is discovered work now.”
- “Close it before wrapping up.”
- `bd create` before the sibling test.

All of these require reapplying this skill before changing tracker state.
