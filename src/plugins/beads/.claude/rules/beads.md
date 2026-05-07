# Beads

Task tracking workflow (run with `dangerouslyDisableSandbox: true`).

`bd <command> [args]` — Types: bug | feature | task | epic | chore
Priority: 0-4 / P0-P4 (0=critical, 2=medium, 4=backlog). NOT "high"/"medium"/"low".

**Basic workflow**: `bd ready` → pick a bead → `start-bead <id>` → molecule executes → `merge-and-cleanup`

**Rules**:
- Use bd for ALL tracking, `--json` for programmatic use
- No markdown TODO lists unless user explicitly requests
- Acceptance criteria: "Build passes. Typecheck passes. Tests pass."
- Epic children parallel by default — only explicit deps create sequence
- For bead-tracked work, specs may be written directly into the bead description (`bd update <id> --description "..."`) — the bead is the plan file
- **`bd create` is pure capture — no claim, no implementation.** Never say "starting work" / "beginning" when the user asks to create/file/capture/track a bead. Reserve "Starting work on task [id]..." strictly for when the user explicitly directs you to START WORK on a specific bead identifier.

## Parent-chain invariants

These are mechanical invariants that every entry point into work on a
bead must uphold — whether you're running a formula step, taking the
trivial inline route in `start-bead`, or filing discovered work
mid-implementation. "I'll just do a quick thing" is not an exemption.

**I1. Claim walk — when work starts on a child, walk UP.**

Before any work (including brainstorming), mark the bead AND every
ancestor epic `in_progress`. Brainstorming is work — a bead that is
actively being brainstormed must never appear as `open` in `bd ready`.

```bash
bd update <id> --status in_progress
PARENT=$(bd show <id> --json | jq -r '.[0].parent // empty')
while [ -n "$PARENT" ]; do
  bd update "$PARENT" --status in_progress
  PARENT=$(bd show "$PARENT" --json | jq -r '.[0].parent // empty')
done
```

**I2. Close walk — when work completes, walk UP and close what's empty.**

After closing a child, walk the parent chain and close each ancestor
epic whose remaining children are all closed. Stop at the first
ancestor that still has any non-closed children (`open` or
`in_progress`), or when there is no parent.

```bash
bd close <id> --reason "<summary>"
PARENT=$(bd show <id> --json | jq -r '.[0].parent // empty')
while [ -n "$PARENT" ]; do
  NON_CLOSED=$(bd list --parent="$PARENT" --json | jq '[.[] | select(.status != "closed")] | length')
  [ "$NON_CLOSED" = "0" ] || break
  bd close "$PARENT" --reason "All children closed"
  PARENT=$(bd show "$PARENT" --json | jq -r '.[0].parent // empty')
done
```

**I3. Discovered-work placement — siblings go IN the epic, not beside it.**

When work is discovered mid-implementation, capture it immediately
(don't defer, don't fix inline). Decide placement with the **sibling
test**:

> **Sibling subtask**: work the parent epic's original decomposition
> should have included as a peer bullet — something that exists on its
> own merits, not only because of how the current bead is being
> implemented.

- **Passes the sibling test** → create with `--parent <epic-id>` so it
  lands in the epic alongside its siblings.
- **Fails the sibling test** (sub-step of the current bead, or only
  tangentially related) → create as an orphan and link with:
  `bd dep add <new-id> <current-id> --type discovered-from`

The test: "would this have been on the epic's original plan, if we'd
thought of it?" Yes → sibling. No → orphan + dep.

**Other parent/child expectations:**
- Before user review → run completion gate pipeline
  (I1's claim walk already surfaces the parent chain for AC / sibling
  context — no separate `bd show <parent-id>` lookup needed)

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

Labels track state through the pipeline. Most apply to beads; a few
apply to molecules (the `Set by` and `Meaning` columns note the subject):

| Label | Set by | Meaning |
|-------|--------|---------|
| `brainstormed` | brainstorm-bead formula (finalize step) | Spec written and reviewed |
| `implementation-ready` | brainstorm-bead formula (finalize step) | Ready for implement-bead / run-queue |
| `implementation-readied-session-<sid>` | brainstorm-bead formula (finalize step) | Marks a session that applied `implementation-ready`; used by `start-bead` Route A for same-session gating. `<sid>` is the first 8 hex chars of the applying session's ID. |
| `for-bead-<bead-id>` | `start-bead` when it creates a brainstorm wisp, and `implement-bead` when it creates an implementation molecule | Applied to the molecule (not the bead). Gives `start-bead` / `implement-bead` a reliable lookup edge from bead to molecule — see "Molecule → bead linkage convention" below. |
| `human` | Any agent via `bd label add <id> human`, applied **only to escalation beads or `[h]` follow-up beads** — never to source beads | **Visibility tag for `bd human list`. NOT a gate on `bd ready`** — only blocking deps gate readiness. Source beads pause via a blocking dep on a `human`-labeled escalation bead per the Human-Escalation Pattern (HEP) below. Resolution uses `bd human respond` / `bd human dismiss` (or `verified-by-human` + `bd close` for `[h]` follow-ups), never bare label removal. Note: `bd human <id>` (no subcommand) is the help command, NOT a label applier — use `bd label add <id> human` instead, then `bd update <id> --append-notes "..."` to attach context. |
| `ralf:required` | `brainstorm-bead` formula (finalize step) or manual label set | Beads formula-step dispatch signal. Implement stages pass target/spec/DoD/context into `ralf-implement`; review stages use it only when their specific formula step explicitly reads the label and passes target/criteria/context into `ralf-review`. |
| `ralf:cycles=N` | Any actor setting an override (typically `brainstorm-bead.finalize`) | Optional max-cycle override that the formula reads and passes to the invoked RALF skill. Setters MUST remove existing `ralf:cycles=` labels before adding a replacement; `bd label remove` accepts exact labels, so list matching labels first rather than passing a wildcard. |

Label commands:
```bash
bd label add <id> <label>
bd label remove <id> <label>
bd label list <id>
bd ready --label <label>
```

---

## Human-Escalation Pattern (HEP)

When an agent stage cannot proceed without human input, it must NOT
stamp `human` on the source bead. The `human` label is a *visibility
tag* (it surfaces beads in `bd human list`); it is **not** a gate on
`bd ready`. The only mechanism that excludes a bead from the ready
queue is an open blocking dependency. The pause is therefore modeled
as a dep on a freshly-created escalation bead, not as a label on the
source.

See `docs/specs/bead-pipeline-architecture.md` §5.6 for the full
protocol; what follows is the operational summary every agent needs.

> **Rollout status (as of this rule).** The `resolve-human-bead` skill
> and `/resolve-human-bead` slash command referenced below are
> implementation-ready (bead `agents-config-7bk.13`) but not yet present
> in the plugin tree. Two upstream-producer retrofits are also pending:
> `merge-or-handoff` formula step (`agents-config-7bk.13.2`) and
> `implement-bead` skill escalation path (`agents-config-7bk.13.3`).
> Until they land, resolve HEP escalations using the documented
> primitives directly: `bd human respond` / `bd human dismiss` for
> Scenarios A–E, `bd label add verified-by-human` + `bd close` for `[h]`
> follow-up Scenario F, and `/merge-and-cleanup` for merge-gate
> Scenario G.

> **Doc duplication note.** The escalation bash snippet below is
> byte-identical with §5.6's; this is the lockstep boundary. **Any
> change to the snippet here MUST land in §5.6 in the same commit, and
> vice versa.** The surrounding prose may be condensed in this file as
> an operational summary — divergence in prose is acceptable, divergence
> in the snippet is a contract violation.

**Escalation (when blocked):**

```bash
HUMAN_ID=$(bd create \
    --title "Human input needed: <one-line summary>" \
    --type task \
    --priority "<inherited from source bead>" \
    --description "<context: what the stage was doing, what is blocked, what is needed>" \
    --json | jq -r '.id')
bd label add "$HUMAN_ID" human
bd update "$HUMAN_ID" --append-notes \
    "Source: <source-bead-id>
Step-bead: <step-bead-id>
Molecule: <mol-id>
Worktree: <worktree-path>
Scenario hint: <one of: spec-amended | scope-expanded | tooling-credentials | architectural-rework | abandoned>"
bd dep add "<source-bead-id>" "$HUMAN_ID"
bd update "<source-bead-id>" --status open
# Exit cleanly (zero exit code; stage is paused, not failed).
```

After this:

- Source bead does NOT carry `human`; it has an open dep blocker on
  `$HUMAN_ID`.
- `bd ready` filters the source bead out (open blocker).
- `bd human list` shows `$HUMAN_ID` for human triage.
- Worktree and `worktree-path-*` molecule label preserved IF PRESENT
  at the point of escalation. Preflight-stage escalations may have no
  worktree yet (per §5.6's preflight carve-out) — that is fine.
- Reverting source `in_progress → open` does NOT revert ancestor epics
  (I1 claim-walk is upward-only; child status changes don't propagate
  up).

**Resolution:** never bare-remove the `human` label. Use
`bd human respond <human-id> --response "..."` for scenarios where
work should resume, or `bd human dismiss <human-id>` for abandonment.
The skill `resolve-human-bead` (slash command `/resolve-human-bead`)
walks the human through scenario diagnosis and applies the correct
primitive. The escalation closes; the dep is satisfied; the source
bead reappears in `bd ready` on the next poll cycle.

**Special case: `[h]` follow-up beads** (architecture doc §4.3) use a
DIFFERENT mechanism — parent-child + I2 close-walk + `verified-by-human`
label — and gate the source bead's *closure* rather than its *readiness*.
Do NOT use the HEP escalation procedure for shift-right verification
beads; they have their own distinct lifecycle.

**Special case: merge-gate hand-off** (`[Merge gate] <source-title>`-titled
escalation bead carrying `human` + `merge-ready`, created by `merge-or-handoff`'s
hand-off path). Resolution is `/merge-and-cleanup` on the source bead, NOT
`bd human respond/dismiss` on the escalation. `resolve-human-bead` detects
the `merge-ready` discriminator and routes accordingly.

`resolve-human-bead` handles all three classes (HEP escalation, `[h]`
follow-up, merge-gate hand-off) via class-detection.

---

## Molecule → bead linkage convention

Molecules created for a bead via `bd mol pour` or `bd mol wisp` have NO
structural link back to the bead they were poured/wisped for: `parent`
is `null` and neither title nor description encodes the bead id (beads
`lp3`, upstream bug). Until `bd` fixes this, skills stamp an explicit
lookup label on the molecule immediately after pour/wisp:

```bash
bd label add <mol-id> for-bead-<bead-id>
```

The `for-bead-<bead-id>` label applies to the **molecule root**, not the
bead itself. It is the convention behind the existence probes in
`start-bead` Step 2 and `implement-bead` Step 2.

**Existence probe** — canonical form for "does an active molecule exist
for this bead?":

```bash
bd list --label for-bead-<bead-id> --type molecule --json \
  | jq '[.[] | select(.status != "closed")]'
```

Two bugs make the `--json` part non-negotiable: the tree-mode text path
silently drops `--type` / `--parent` filters and seeds the queried id
into its output (beads `2dx`). `--json` flips `prettyFormat` off in `bd`
and routes through the direct filtered query, so both `--label` and
`--type` are honored.

**Why label, not reparenting**: setting `parent = <bead-id>` on the
molecule would entangle lifecycles — the I2 close-walk would cascade-close
the bead when the molecule squashes, which is wrong (molecule steps done
≠ bead delivered/merged). Labels are lifecycle-neutral and already the
idiom for cross-cutting tags.

**When the upstream bugs land**: once `bd` fixes `2dx` (tree path honors
filters) and `lp3` (`bd mol pour` sets `parent = <bead-id>` or adds a
structural edge), this convention becomes redundant. Drop the stamp and
switch the probe to `bd list --parent <bead-id> --type molecule --json`.

---

## Skill Pipeline

The full bead lifecycle runs through four skills:

1. **`create-bead`** — capture an idea as a placeholder (fast, no spec)
2. **`start-bead`** — route to brainstorm or implement based on readiness
3. **`implement-bead`** — pour formula, orchestrate subagents through DAG
4. **`run-queue`** — autonomous loop: find implementation-ready beads, process them

Plus formulas:
- `brainstorm-bead` — interactive spec writing + RALF spec review → `implementation-ready`
- `implement-feature` — label-driven implementation (`ralf-implement` when `ralf:required`, otherwise TDD + domain skills); red-tests hard-escalates + auto-reroutes to `formula-docs-only` when no test runner OR no `[m]` AC lines
- `fix-bug` — root-cause diagnosis + label-driven implementation (`ralf-implement` when `ralf:required`, otherwise TDD + domain skills); red-tests hard-escalates + auto-reroutes to `formula-docs-only` when no test runner (Trigger A only — Trigger B omitted to preserve regression-test invariant)
- `docs-only` — single-pass pipeline for work with no code tests (docs/spec/prose/config-only edits); no red-tests / no green-loop / no quality-sweep; verify-ac warn-and-passes when zero `[m]` ACs
- `merge-and-cleanup` — retroactive gate + explicit auth → merge

---

## Session Separation

**`run-queue` runs in a dedicated Claude session.**
Do NOT run run-queue in the same session where brainstorming is happening.
The polling loop and background subagents will interrupt interactive conversations.

- Brainstorming session: interactive, user present, no background work
- run-queue session: autonomous, separate window/terminal, no brainstorming
- **Post-brainstorm hand-off**: Any bead that becomes
  `implementation-ready` in the current session is a hand-off candidate
  by default. Implementation runs in a separate run-queue session;
  continuing in the current session requires explicit user authorization
  per session. The rule has two enforcement tiers:
  - **Mechanical** (brainstorm-bead formula): the formula stamps an
    `implementation-readied-session-<sid>` label, so `start-bead` Route A
    auto-gates against the originating session.
  - **Advisory** (manual `bd label add`, imports, or any other path that
    doesn't stamp the session marker): Route A cannot auto-gate, but the
    rule still applies — the agent should honor the hand-off boundary by
    judgment. If manual/import paths will be common in your workflow,
    stamp a session marker yourself to make the gate mechanical.

---

## Skill Partnership

Beads and superpowers are partners with distinct roles. Do not confuse them.

- **Beads = OUTER lifecycle** — what work exists, its state, dependencies, and
  multi-session persistence. The bead is the plan. Formulas define the workflow
  at authoring time; at runtime the agent drives the resulting molecule.
- **Superpowers = INNER methodology** — *how* to actually do the work at each
  step. Skills are invoked *inside* molecule steps, not as peers of the bead
  workflow.

### Inner methodology skills (partners — use freely inside molecule steps)

- `superpowers:brainstorming`
- `superpowers:systematic-debugging`
- `superpowers:root-cause-tracing`
- `superpowers:test-driven-development`
- `superpowers:verification-before-completion`
- `superpowers:using-git-worktrees`
- `superpowers:finishing-a-development-branch`
- `superpowers:requesting-code-review`
- `superpowers:receiving-code-review`
- `wait-for-pr-comments`
- `reply-and-resolve-pr-threads`
- `superpowers:dispatching-parallel-agents`
- `ralf-review`
- `ralf-implement`

### Off-limits for bead-tracked work (compete with bead lifecycle)

- `superpowers:writing-plans` — the bead description IS the plan
- `superpowers:executing-plans` — `implement-bead` is the executor
- `superpowers:subagent-driven-development` — `implement-bead` orchestrates via the formula DAG

**Rule:** off-limits skills compete with the bead lifecycle. On a bead, use
`start-bead` → `brainstorm-bead` → `implement-bead` instead. Off-limits skills
remain available for non-bead work.

---

## Notes vs Comments: bd update semantics

Three commands serve distinct roles — mixing them up causes lost context.

| Command | Semantics | When to use |
|---|---|---|
| `bd update <id> --append-notes "..."` | Appends to existing notes | Step output, escalation context, cumulative status, run breadcrumbs |
| `bd update <id> --notes "..."` | **Replaces** existing notes entirely | Initial bead creation, or `brainstorm-bead` spec writes — intentional overwrites only |
| `bd comments add <id> "..."` | Creates a separate, non-destructive comment | Lifecycle audit breadcrumbs, molecule→bead tracing, events that should not pollute notes |

**Footgun alert**: `--notes` is a destructive overwrite. If you mean "add to this", use `--append-notes`.
