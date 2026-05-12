# Beads

Task tracking workflow (run with `dangerouslyDisableSandbox: true`).

`bd <command> [args]` — Types: bug | feature | task | epic | chore | decision
Priority: 0-4 / P0-P4 (0=critical, 2=medium, 4=backlog). NOT "high"/"medium"/"low".

**Basic workflow**: `bd ready` → pick a bead → `start-bead <id>` → molecule executes → `merge-and-cleanup`

**Rules**:
- Use bd for ALL tracking, `--json` for programmatic use
  - `bd show --json` emits literal newlines in `notes`/`description`/`acceptance_criteria` — jq rejects them; use Python: `bd show <id> --json | python3 -c "import sys,json; d=json.load(sys.stdin)[0]; print(d.get('notes',''))"`
  - Single-line fields (`id`, `title`, `status`, `labels`, `dependencies`) are safe for jq
- No markdown TODO lists unless user explicitly requests
- Acceptance criteria: "Build passes. Typecheck passes. Tests pass."
- Epic children parallel by default — only explicit deps create sequence
- Specs go in bead fields (--description, --notes, --design, --acceptance) — the bead IS the plan. If a write balks at field size (TEXT holds ~65KB; unlikely but possible with very large specs), externalize to docs/beads/<short-id>-<<slug>.md and put a relative-path reference in the field. The bead remains the owner; the file is overflow storage.
- **`bd create` is pure capture — no claim, no implementation.** Reserve "Starting work on task [id]..." for when the user explicitly directs you to START WORK on a specific bead identifier.
- When referencing any bead in conversation turn, always use the ID and title together, e.g. "bd-1234 (Implement login)"; you only need do this once per turn per bead, then you can refer to it by ID alone for the rest of the turn.

## Parent-chain invariants

**I1. Claim walk — when work starts on a child, walk UP.**

Before any work (including brainstorming), mark the bead AND every ancestor epic `in_progress`:

```bash
bd update <id> --status in_progress
PARENT=$(bd show <id> --json | jq -r '.[0].parent // empty')
while [ -n "$PARENT" ]; do
  bd update "$PARENT" --status in_progress
  PARENT=$(bd show "$PARENT" --json | jq -r '.[0].parent // empty')
done
```

**I2. Close walk — when work completes, walk UP and close empty ancestors.**

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

When work is discovered mid-implementation that does not fit the spirit of the current scope's requirements, capture it immediately. **Sibling test**: "would this have been on the epic's original plan?"
- Yes → `bd create --parent <epic-id>`
- No → `bd create` (orphan) + `bd dep add <new-id> <current-id> --type discovered-from`

## "bd ready" / "what's next" Behavior

Use the `whats-next` skill. It handles mode selection (human-triage + brainstorm list vs. implementation-ready list), sort order, and empty-section suppression. `run-queue` is exempt — it calls `bd ready --label implementation-ready` directly in its autonomous context.

## Notes vs Comments

| Command | Semantics | When to use |
|---|---|---|
| `bd update <id> --append-notes "..."` | Appends to notes | Step output, escalation context, run breadcrumbs |
| `bd update <id> --notes "..."` | **Replaces** notes entirely | Initial creation or intentional spec overwrites only |
| `bd comments add <id> "..."` | Non-destructive comment | Lifecycle audit, molecule→bead tracing |

**Footgun**: `--notes` is a destructive overwrite. Use `--append-notes` to add.

## Human-Escalation Pattern (HEP)

When a stage cannot proceed without human input, it executes the
**Human-Escalation Pattern (HEP)** rather than stamping `human` directly
on a source or step bead. HEP is defined in full in
`docs/specs/bead-pipeline-architecture.md` §5.6 (authoritative); this
section is the operational summary every agent needs at hand.

**Critical premise.** The `human` label is a *visibility tag* on
`bd human list` — it is **not** a gate on `bd ready`. Only an open
blocking dep keeps a bead out of the ready queue. Stamping `human` on a
source bead would leave it visible to `bd ready --label implementation-ready`,
letting another agent silently grab paused work.

**Escalation procedure (run literally on every flag-human path):**

```bash
# dual-shape contract: bd create --json may emit either {id:...} or [{id:...}]
HUMAN_ID=$(bd create \
    --title "Human input needed: <one-line summary>" \
    --type task \
    --priority "<inherited from source bead>" \
    --description "<context: what was being done, what is blocked, what is needed>" \
    --json | jq -r 'if type == "array" then .[0].id else .id end // empty')
[ -z "$HUMAN_ID" ] && { echo "HEP: failed to extract escalation bead id" >&2; exit 1; }
bd label add "$HUMAN_ID" human
bd update "$HUMAN_ID" --append-notes \
    "Source: <source-bead-id>
Step-bead: <step-bead-id>
Molecule: <mol-id>
Worktree: <worktree-path-or-N/A>
Scenario hint: <spec-amended | scope-expanded | tooling-credentials | architectural-rework | abandoned>"
bd dep add "<source-bead-id>" "$HUMAN_ID"
bd update "<source-bead-id>" --status open
# Exit cleanly (zero exit code; stage is paused, not failed).
```

**Single-bead `human` invariant.** Only the escalation bead carries
`human`. On HEP flag-human paths, the source bead never carries `human`
and the step-bead never carries `human`. (Exception: the current
`merge-or-handoff` formula implementations stamp `merge-ready` + `human`
on the source bead directly rather than creating a separate escalation
bead — a divergence from arch §5.6 tracked in `agents-config-g17x`.)
`[h]` follow-up beads (§4.3) also carry `human` but are a separate
class with their own lifecycle.

**Resolution.** Use the `resolve-human-bead` skill (`/resolve-human-bead
<bead-id>`). It detects the bead's class — merge-gate hand-off (G),
`[h]` follow-up (F), HEP escalation (A–E), orphan, inconsistent-state
repair, or source-bead pivot — and applies the right primitive:
`bd human respond` (A–D), `bd human dismiss` + `bd close <source-id>`
(E), `verified-by-human` + plain `bd close` (F), or
`/merge-and-cleanup` (G).

**Bare label removal is prohibited.** `bd label remove <human-id>
human` bypasses the audit trail and leaves the dep blocker live; the
escalation disappears from `bd human list` but the source remains
paused with no recorded reason. Always close through the
audit-trail-preserving primitive.

## Session Separation

**`run-queue` runs in a dedicated Claude session.**

- Brainstorming session: interactive, user present
- run-queue session: autonomous, separate window/terminal

**Post-brainstorm hand-off**: Beads that become `implementation-ready` in the current session require explicit user authorization to implement in the same session. The `brainstorm-bead` formula stamps `implementation-readied-session-<sid>` so `start-bead` Route A auto-gates; for manual label paths, honor the boundary by judgment.
