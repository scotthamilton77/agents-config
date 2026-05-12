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

## Session Separation

**`run-queue` runs in a dedicated Claude session.**

- Brainstorming session: interactive, user present
- run-queue session: autonomous, separate window/terminal

**Post-brainstorm hand-off**: Beads that become `implementation-ready` in the current session require explicit user authorization to implement in the same session. The `brainstorm-bead` formula stamps `implementation-readied-session-<sid>` so `start-bead` Route A auto-gates; for manual label paths, honor the boundary by judgment.
