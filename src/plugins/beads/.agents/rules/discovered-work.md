# Discovered-Work Discipline

When mid-task work surfaces a new issue, adjudicate scope FIRST, then file with a
roadmap anchor. Never file-and-forget: every discovery either gets fixed now or
gets a triaged, anchored bead plus a row in the completion report's
discovered-work manifest.

**Sibling test:** *would this have been on the current work item's original plan/spec?*

## In scope → fix it in this session (default)

In-scope discoveries are part of the work you were asked to do — do them now, in
the current session/PR. "Discovered work" is not a deferral service for missed
scope. Deferring in-scope work is permitted ONLY via three escape hatches:

- **externally-blocked** — needs credentials, an upstream fix, or another PR to land first
- **blast-radius** — the fix crosses into a subsystem or risk class the current change doesn't already touch
- **own-cycle** — big enough to deserve its own design/tests/review cycle (heuristic: would roughly double the current diff)

Every deferral requires ALL of:

1. File as a **sibling** of the in-flight bead: `bd create --parent <parent-of-in-flight-bead>` — keeps the in-flight bead closeable while the
   family holds the deferred work. (No in-flight bead, or it has no parent →
   anchor per the out-of-scope procedure below, recording session/PR provenance
   in the triage block.)
2. The triage block (below) with `Scope: in-scope — deferred: <hatch> — <why>`.
3. An escalation line in the completion report's **Remaining Work** section —
   not just the discovered-work manifest.
4. Do NOT close the filed bead this session.

## Out of scope → file it anchored

- **Parent = best-fit epic under the milestone the work maps to**; no fitting
  epic → the milestone itself: `bd create --parent <anchor-id>`. Apply the
  project's label conventions.
- **Provenance edge too**: `bd dep add <new-id> <current-work-id> --type discovered-from`. Provenance is not placement — both edges, always.
- **Orphan is a loud exception**: permitted only when genuinely no milestone
  fits, and the completion report must escalate it ("fits no milestone — may be
  out of project scope, needs a human call").

## Triage block (required on every discovered-work bead)

Append to the bead description:

```
## Triage
- Scope: out-of-scope — <one line why>   (or: in-scope — deferred: <hatch> — <why>)
- Priority: P<N> — <one line why>
- Anchor: <epic-or-milestone-id> — <one line why>
```

## Close-walk safety

Never file a discovery as a child of the in-flight bead itself, and never close a
newly filed discovery mid-session. Close-walk closes a parent the moment all its
structural children are closed — filing under the in-flight bead and closing the
child can auto-close in-flight work while it is still pending. Recovery needs
`bd reopen <parent>` plus an audit of beads the close-walk propagated through.
Classify with the sibling test BEFORE filing, not after.
