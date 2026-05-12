---
name: resolve-human-bead
description: >
  Use when a user invokes `/resolve-human-bead <bead-id>`, expresses intent
  to resolve/fix/address a human-flagged bead, or when `start-bead` Route D
  dispatches here because the target bead carries `human` itself or has an
  open `bd dep` blocker carrying `human`. Detects the bead's class via
  priority-ordered probes and applies the right resolution primitive
  interactively, with user confirmation on destructive actions.
model: sonnet[1m]
effort: high
---

# resolve-human-bead

Resolve a human-flagged bead back into the autonomous pipeline.

The skill detects what *kind* of human-labeled state the target represents,
then applies the right primitive. It NEVER bare-removes the `human` label
and NEVER bare-closes a `human`-labeled bead — both bypass the audit trail.

## Authoritative references

This skill implements the **Human-Escalation Pattern (HEP)** defined in:

- `docs/specs/bead-pipeline-architecture.md` **§5.6** — full HEP protocol,
  class taxonomy, scenario tables (A–G), and the merge-gate sub-class
  contract. Cite as authority on every design question.
- The HEP section of `src/plugins/beads/.claude/rules/beads.md` — operational
  summary every agent needs at hand. Same authority, more terse.

`[h]` follow-up beads (§4.3) are a separate class — see the class taxonomy
in §5.6's "`[h]` follow-up beads are NOT HEP" subsection.

## When to Use

- User runs `/resolve-human-bead <bead-id>` (the slash-command wrapper).
- `start-bead` Route D dispatches here for a bead that carries `human` itself
  OR has an open `bd dep` blocker carrying `human`.
- User says "resolve the human bead", "address the human-flagged bead",
  "the escalation on `<id>`".

## 1. Class detection (priority-ordered — first match wins)

Class detection ordering is **load-bearing**. Run the six probes in this
exact order:

- A `[Merge gate]`-titled bead also satisfies the generic HEP-escalation
  predicate (it carries `human` + has an incoming dep edge), so the
  merge-gate probe MUST run first or scenario routing is wrong.
- The inconsistent-state probe MUST run BEFORE the orphan probe.
  Probe 4 (orphaned-escalation sub-case (a)) — the escalation bead is
  open but its source is closed — also satisfies the orphan probe's
  "no incoming dep edge from any *open* source" predicate. If the
  orphan probe runs first, the orphaned-escalation case is silently
  downgraded to "treat as standalone task" and the integrity-repair
  branch is never reached.

### Probe 1 — Merge-gate hand-off sub-class

Triggered when ALL of the following hold on the target bead:

- has `human` label
- has `merge-ready` label
- title prefix is `[Merge gate]`

Created by `merge-or-handoff`'s hand-off path (arch §3, §5.6). Resolution
routes to **Scenario G** (`/merge-and-cleanup`). Do NOT use `bd human
respond` or `bd human dismiss` on a merge-gate hand-off escalation —
`/merge-and-cleanup` owns its closure as part of the merge transaction.

### Probe 2 — [h] follow-up

Triggered when ALL of the following hold:

- has `human` label
- has `parent` set (parent-child edge to a source bead)
- title prefix is `[Human verify]`

Created by `brainstorm-bead.finalize` (arch §4.3). Resolution routes to
**Scenario F** (`verified-by-human` + plain `bd close`).

### Probe 3 — HEP escalation

Triggered when ALL of the following hold:

- has `human` label
- has at least one **incoming** `bd dep` edge from a non-closed source bead
- lacks the discriminators above (no `merge-ready`, no `[Merge gate]`/`[Human verify]`
  title prefix)

Resolution routes to **Scenarios A–E** (depending on the user's diagnosis).

### Probe 4 — Inconsistent-state repair branch

Distinct from Scenario G/G-merge above. Evaluated BEFORE the orphan
probe because sub-case (a) below also satisfies the orphan predicate
("no incoming dep edge from any open source"); the orphan probe must
not silently absorb it. Triggered when EITHER:

- (a) **Orphaned escalation** — the escalation bead is `open` but its
  source bead is already `closed`. The dep blocker is moot; the
  escalation has nothing to gate.
- (b) **Stale dep** — the escalation bead is `closed`, but a non-closed
  source still has an open `bd dep` edge pointing at it (someone
  bare-`bd close`d the escalation, leaving the dep edge live).

Surface the inconsistency to the user. **Do NOT silently auto-resolve.**
The skill surfaces these cases without auto-resolving so the user can
audit how the inconsistency arose.

Offer concrete repair actions and let the user pick one:

- Orphaned-escalation repair option: `bd human dismiss <human-id> --reason
  "Source already closed; escalation orphaned"` (close the orphaned
  escalation through the audit-trail-preserving primitive).
- Stale-dep repair option: `bd dep remove <source-id> <human-id>` (clear
  the stale dep edge so the source unblocks).

Always quote the exact id and reason on the repair-action confirmation
prompt; the user attests the repair before any state change.

### Probe 5 — Orphan human task

Triggered when:

- has `human` label
- has no incoming `bd dep` edge from any source (open or closed) —
  i.e., truly dep-less, not the closed-source case (which Probe 4
  already claimed as the orphaned-escalation sub-case)
- has no `[h]` or `[Merge gate]` discriminator

Treat as a standalone task. Prompt the user for intent — most likely
Scenario E (abandon via `bd human dismiss`), or a user-specific close.

### Probe 6 — source-bead pivot

Triggered when the user invoked `/resolve-human-bead <source-id>` on a
source bead that itself carries no `human` label but has at least one
open `human`-labeled blocker.

**Canonical detection probe** — verified jq paths inline. The `bd show
--json` `dependencies[]` shape was verified live before shipping: each
dep object exposes `dependency_type` (the relationship type) and `.id`
(the blocker's bead id). The `.type` / `.issue_id` shape is **bd ready
--json**'s dependency record shape, NOT bd show's — using it here
returns empty results silently:

```bash
# List source's open dep blockers, then check each for the human label.
bd show <source-id> --json \
  | jq -r '.[0].dependencies[]? | select(.dependency_type=="blocks") | .id' \
  | while read blocker; do
      BSTATE=$(bd show "$blocker" --json | jq -r '.[0].status')
      [ "$BSTATE" = "closed" ] && continue
      bd label list "$blocker" --json | jq -e 'index("human")' >/dev/null && echo "$blocker"
    done
```

The skill pivots to the discovered blocker and re-runs class detection
on it.

#### Multi-blocker handling

If the source has more than one open `human`-labeled blocker
(**multi-blocker** case — also stated as "multiple human-labeled
blockers" / ">1 blocker" / "more than one blocker"), the skill lists
them all with one-line context per blocker and prompts the user to pick
one. **Resolve one per invocation.** This is the list-and-prompt UX —
the skill prompts user to pick which blocker to address; subsequent
blockers are resolved by re-invoking the skill.

List shape (one line per blocker; title + status + age):

```
Multiple human-labeled blockers on <source-id>:
  1. <blocker-id-1> — "<title>" — status=<s> — opened <age>
  2. <blocker-id-2> — "<title>" — status=<s> — opened <age>
Pick one to resolve (1/2/...): _
```

## 2. Destructive-action enumeration

The following primitives are destructive and require **explicit user
confirmation** before invocation. The confirmation prompt MUST quote the
exact id and the exact reason about to be applied.

- `bd mol squash <mol-id>` (Scenario D — clears stale molecule state).
- `bd human dismiss <human-id>` (Scenario E — closes the escalation with
  reason "Dismissed").
- `bd close <source-id>` (Scenario E — abandons the source bead; this is
  the only scenario in which the skill closes a source bead directly).

Scenario G's destructive actions (PR merge, branch deletion, worktree
teardown) are owned by `/merge-and-cleanup`, which has its own
confirmation contract; `resolve-human-bead`'s only action in G is to
invoke `/merge-and-cleanup`.

## 3. Scenarios

Quick summary — each scenario's resolution primitive on **one physical line** (the detailed step-by-step subsections follow below):

- Scenario A. Spec amended (HEP class) — Description-edit on source bead BEFORE close via `bd human respond <human-id> --response "..."`.
- Scenario B. Scope expanded (HEP class) — `bd create --type task --title "..."` + `bd dep add <source-id> <new-id>` BEFORE `bd human respond <human-id> --response "..."`.
- Scenario C. Tooling/credential resolved (HEP class) — ONLY `bd human respond <human-id> --response "..."`; no other state changes.
- Scenario D. Architectural rework (HEP class) — `bd mol squash <mol-id> --summary "..."` (with user confirmation, destructive) BEFORE `bd human respond <human-id> --response "..."`.
- Scenario E. Abandoned (HEP class) — `bd human dismiss <human-id>` (with confirmation) AND `bd close <source-id>` (with separate confirmation); MUST NOT invoke `bd human respond`.
- Scenario F. [h] follow-up verified ([h] follow-up class) — `bd label add <follow-up-id> verified-by-human` AND plain `bd close <follow-up-id>`; NOT `bd human respond`, NOT `bd human dismiss`.
- Scenario G. Merge-gate cleared (merge-gate hand-off sub-class) — `/merge-and-cleanup <source-id>`; MUST NOT invoke `bd human respond` or `bd human dismiss` on the hand-off escalation directly.

### Scenario A — Spec amended (HEP escalation class)

The user determines the source bead's spec needs amending to reflect
correct intent. Description-edit step happens BEFORE the close primitive.

1. **Description-edit step** — the user edits the source bead's
   description (manually or via skill-prompted text editor). The skill
   surfaces the current description and prompts the user to write the
   amendment.
2. Close the escalation:

   ```bash
   bd human respond <human-id> --response "<one-line summary of amendment>"
   ```

`bd human respond` is the close primitive for Scenario A — it adds the
response as a comment and closes the escalation. The description-edit
step MUST come BEFORE the `bd human respond` call so the source bead
already reflects the agreed amendment when the escalation closes and
the source bead unblocks.

### Scenario B — Scope expanded (HEP escalation class)

The user determines the work expanded in scope, so a new sibling bead
captures the extra scope. `bd create` and `bd dep add` happen BEFORE
the `bd human respond` close.

1. Prompt the user for the new sibling bead's title and description.
2. Create it:

   ```bash
   bd create --title "<new-title>" --type task --description "<new-description>" --priority "<inherit from source>"
   ```

3. Add the dep edge:

   ```bash
   bd dep add <source-id> <new-id>
   ```

4. Close the escalation:

   ```bash
   bd human respond <human-id> --response "<scope expansion noted, dep added>"
   ```

The order is mandatory: `bd create` and `bd dep add <source-id> <new-id>`
BEFORE `bd human respond`. If the escalation closes first, the source
bead unblocks immediately and may be picked up by another agent before
the new dep edge lands.

### Scenario C — Tooling/credential resolved (HEP escalation class)

The blocker was a tooling or credential gap that has since been
resolved. Apply ONLY `bd human respond <human-id>`; no other state
changes. The skill MUST NOT edit the source description, create
sibling beads, squash molecules, or touch any other bead.

```bash
bd human respond <human-id> --response "<what was resolved>"
```

Scenario C uses only `bd human respond` — no other state changes apply.

### Scenario D — Architectural rework (HEP escalation class)

The blocker reveals the molecule's accumulated state is no longer valid
and must be reset. `bd mol squash` (destructive — requires confirmation)
happens BEFORE the description edit and the `bd human respond` close.

1. Prompt the user for confirmation, quoting the exact `<mol-id>` and
   the rework summary string about to be applied:

   ```
   About to squash molecule <mol-id> with summary "<summary>".
   This is destructive and resets the molecule's accumulated state.
   Proceed? (y/n): _
   ```

2. On confirmation, squash the molecule:

   ```bash
   bd mol squash <mol-id> --summary "<rework summary>"
   ```

3. The user edits the source bead's description to reflect the rework.
4. Close the escalation:

   ```bash
   bd human respond <human-id> --response "<rework noted, molecule reset>"
   ```

The `bd mol squash` step is the destructive primitive and is ordered
BEFORE `bd human respond` so the rework summary is durable before the
source bead unblocks.

### Scenario E — Abandoned (HEP escalation class)

The source bead is no longer worth pursuing. The skill MUST NOT invoke
`bd human respond` in this scenario — the escalation is dismissed, not
responded to. Each destructive action is gated on its own separate
confirmation prompt.

1. First confirmation, quoting `<human-id>` and the dismiss reason:

   ```
   About to dismiss escalation <human-id> with reason "<reason>".
   Proceed? (y/n): _
   ```

2. On confirmation:

   ```bash
   bd human dismiss <human-id> --reason "<why abandoned>"
   ```

3. Second, separate confirmation, quoting `<source-id>` and the close
   reason:

   ```
   About to close source bead <source-id> with reason "<reason>".
   Proceed? (y/n): _
   ```

4. On confirmation:

   ```bash
   bd close <source-id> --reason "<why source abandoned>"
   ```

Scenario E MUST NOT invoke `bd human respond` — `bd human dismiss` is
the correct primitive for abandonment, and the dismissal/close pair
preserves audit trail without implying the work was completed.

### Scenario F — `[h]` follow-up verified (`[h]` follow-up class only)

The user has verified the AC line the follow-up was created to gate.
The close primitive is plain `bd close` (after stamping the
`verified-by-human` label) — **NOT `bd human respond` and NOT `bd
human dismiss`**. The `verified-by-human` label is what
`merge-and-cleanup`'s gate-step inspects (arch §4.3); plain
`bd close` then drives the I2 close-walk so the parent source bead can
close once all follow-up siblings are verified.

1. Stamp `verified-by-human`:

   ```bash
   bd label add <follow-up-id> verified-by-human
   ```

2. Close with plain `bd close`:

   ```bash
   bd close <follow-up-id> --reason "<verification summary>"
   ```

Scenario F MUST NOT invoke `bd human respond` and MUST NOT invoke `bd
human dismiss` — those are HEP-escalation-class primitives; `[h]`
follow-ups close via the parent-child + I2 close-walk path.

### Scenario G — Merge-gate cleared (merge-gate hand-off sub-class only)

The hand-off escalation was created by `merge-or-handoff`'s hand-off
path. The skill defers all action to `/merge-and-cleanup`:

```bash
/merge-and-cleanup <source-id>
```

`/merge-and-cleanup` merges the PR, runs cleanup, and closes the
hand-off escalation bead AND the `merge-{source-id}` close-gate child
as final actions. The skill MUST NOT invoke `bd human respond` or `bd
human dismiss` on the hand-off escalation bead directly —
`/merge-and-cleanup` owns its closure.

**Manual fallback** — if `/merge-and-cleanup` is unavailable, surface
the manual recovery to the user: they merge the PR themselves, then
close the escalation via `bd human respond <human-id> --response
"Merged manually"` once the merge action completed.

## Red Flags

| Thought | Reality |
|---------|---------|
| "I'll just `bd label remove <id> human` to clear the escalation" | NO. Bare `bd label remove <id> human` (or `bd label remove ... human` in any shape) is **prohibited** — it bypasses the audit trail. The escalation bead disappears from `bd human list` but the dep blocker stays live and the source bead is still paused with no recorded reason. Use `bd human respond` (Scenarios A–D) or `bd human dismiss` (Scenario E) for HEP escalations; `verified-by-human` + plain `bd close` for `[h]` follow-ups (Scenario F); `/merge-and-cleanup` for merge-gate (Scenario G). |
| "I'll just `bd close` the human-labeled bead and move on" | NO. Bare `bd close` on a `human`-labeled bead is **prohibited** — it bypasses the audit trail (`bd human respond`/`bd human dismiss` record reasons and add audit comments; plain `bd close` does not). The only exception is Scenario F's plain `bd close` AFTER the `verified-by-human` label has been stamped — that path is deliberate, audit-trail-preserving, and gated by the parent-child + I2 close-walk on `merge-and-cleanup`. |
| "Scenario C also needs me to edit the source description" | NO. Scenario C is the "tooling/credential resolved" case — ONLY `bd human respond`. No other state changes. |
| "Scenario E should use `bd human respond`, the user has 'responded' that the work is abandoned" | NO. Abandoned = `bd human dismiss` + `bd close <source-id>`. `bd human respond` implies the source bead remains live and will resume; that is the opposite of what abandonment means. |
| "Scenario F should use `bd human respond` — there's a human in the loop" | NO. `[h]` follow-ups are structurally distinct from HEP escalations (parent-child + I2 close-walk vs. dep-blocker). `bd human respond` would close the follow-up without stamping `verified-by-human`, breaking `merge-and-cleanup`'s gate-step (arch §4.3). |
| "Multiple human-labeled blockers? I'll resolve them all at once" | NO. List-and-prompt; one resolved per invocation. The user picks one each time. |
| "The source is closed but the escalation is still open — I'll auto-close the escalation" | NO. That is the inconsistent-state class; **surfaces without auto-resolving**. Surface the inconsistency, offer concrete repair actions, and let the user pick. |
| "I'll squash the molecule without asking — it's clearly needed" | NO. `bd mol squash` is destructive — explicit user confirmation, with the exact `<mol-id>` and summary quoted in the prompt. |
| "Merge-gate hand-off? I'll just `bd human respond` it" | NO. The merge-gate sub-class routes to `/merge-and-cleanup` (Scenario G). `bd human respond`/`bd human dismiss` on a merge-gate hand-off escalation bead double-closes against `/merge-and-cleanup`'s own closure transaction. |
