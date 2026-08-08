---
name: triaging-discovered-work
description: Use when a task, test, review, or implementation reveals new work requiring a scope, filing, or deferral decision, including bugs, missing requirements, scope expansions, and mid-task follow-ups that could be incorrectly filed, orphaned, or deferred.
admission:
  prevents: Discovered work used as a deferral channel for work already in scope, and discoveries filed where nothing will find them again — under the in-flight item, or with a provenance edge and no roadmap placement. The pressure at discovery time is a nearly-finished PR, and it bends every judgement the same way.
  cost: A tracker item, with its parentage and provenance edges, that someone has to groom or close later.
  remove_when: Agents mid-task, with this skill unloaded, run the sibling test and name an escape hatch before filing in two consecutive sessions — or the tracker facade starts adjudicating scope rather than form.
---

# Triaging Discovered Work

A mid-task discovery — a bug, a missing requirement, a scope expansion — forces one
decision before anything else: fix it now, or file it. This skill owns that
adjudication. `work discover` owns the filing and refuses a malformed one.

## Iron Law

**NO FILING OR DEFERMENT WITHOUT SCOPE ADJUDICATION.**

Schedule pressure, a nearly-complete PR, or a request to "just create a work item"
do not create an exception. A discovery is not a deferral channel for work already
in scope.

## Decide the scope

Apply the **sibling test**: *would this have been on the current work item's
original plan or spec?*

### In scope — fix it in this session

Do the work in the current session and PR. Deferral is permitted only when one of
three named escape hatches applies:

- **externally-blocked** — credentials, an upstream fix, or another PR must land first
- **blast-radius** — the fix enters a subsystem or risk class outside this change
- **own-cycle** — it needs its own design, tests and review, and would roughly double the diff

File a permitted deferral as a **sibling** of the in-flight item, anchored at that
item's parent:

```bash
work discover --noun bugfix --title "<title>" \
  --scope in-scope-deferred:own-cycle --scope-why "<why this hatch>" \
  --anchor <parent-of-in-flight> --anchor-why "<why here>" \
  --priority P2 --priority-why "<why this priority>" \
  --discovered-from <in-flight-id>
```

If the in-flight item has no parent, there is no sibling anchor to derive. File it
out of scope instead and say so in the rationale.

### Out of scope — file it anchored

Find the best-fit epic beneath the milestone the work maps to. If no epic fits, use
the milestone itself.

```bash
work discover --noun chore --title "<title>" \
  --scope out-of-scope --scope-why "<why out of scope>" \
  --anchor <epic-or-milestone-id> --anchor-why "<why this anchor>" \
  --priority P3 --priority-why "<why this priority>" \
  --discovered-from <current-work-id>
```

**Parentage is placement; `discovered-from` is provenance.** One call writes both
edges. Neither substitutes for the other.

An orphan is allowed only when no milestone fits: `--orphan --escalation-why "…"`
in place of `--anchor`. That is a loud human escalation, not a quiet filing.

Pass `--track NAME` when the anchor carries no track to inherit; the facade names
the configured tracks when it refuses.

## What the facade enforces, and what it does not

`work discover` refuses to file without an anchor or an explicit `--orphan`, without
a non-blank single-line rationale on every triage field, and — for an in-scope
deferral — refuses any anchor that is not the exact parent of `--discovered-from`.
That last refusal is the close-walk guard: a discovery filed as a *child* of the
in-flight item can auto-close its parent when it closes.

It enforces **form**. Scope correctness stays your judgement: whether the sibling
test passes, whether a hatch genuinely applies, and which anchor is right.

## Preserve close-walk safety

Never close a newly filed discovery, or an out-of-scope item's new anchor chain, in
the current session. Closing the last structural child can auto-close its parent
while the in-flight work is still pending. If it happens, recover with
`work reopen <parent>` and audit the propagated closes before continuing.

## Completion reporting

The `work discover` envelope carries a `manifest_row`. Put it in the completion
report's manifest verbatim rather than re-describing the filing. When the envelope's
`remaining_work` is true — every in-scope deferral — add an escalation line under
**Remaining Work** naming the hatch. An orphan is escalated as
`unanchored — needs your call`.

## Rationalizations

| Excuse | Reality |
|---|---|
| "The PR is nearly done; I can file it later." | If it is in scope, fix it now unless a named escape hatch applies. |
| "A provenance edge is enough." | Provenance is not placement; anchor it on the roadmap too. |
| "It has no matching epic, so an orphan is fine." | Use the milestone when one fits; an orphan is a human escalation. |
| "I can close the new item so the board stays tidy." | Closing it can close the in-flight parent through the close walk. |

## Red flags — STOP

- "Just make a work item."
- "We can decide the anchor later."
- "This was in scope, but it is discovered work now."
- "Close it before wrapping up."
- Reaching for `work discover` before the sibling test.

Every one of these requires reapplying this skill before changing tracker state.
