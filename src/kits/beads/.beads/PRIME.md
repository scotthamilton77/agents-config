# Beads — Project Issue Tracker

This project tracks durable work with **bd (beads)**.

## Task tracking

- **bd is for durable work** — issues, discovered follow-ups, anything that must
  outlive the session. File the bead *before* writing code for it; mark it
  in-progress when you start.
- **In-session planning is yours** — use your native Task / ToDo tools freely to
  plan and track the steps of the work you're doing right now. bd tracks *what*
  needs doing across sessions; your task list tracks *how* you execute it in this session.
- Don't run `bd edit` — it opens `$EDITOR` and hangs a non-interactive agent.
  Edit fields inline: `bd update <id> --title/--description/--notes/--design`.

## Essential commands

```bash
bd --help  /  bd <command> --help   # authoritative flag reference — read before guessing
bd ready                            # claimable work (no open blockers) — default 100 rows
bd list                             # open issues — default 50 rows; --all includes closed
bd show <id>                        # full detail + dependencies
bd update <id> --claim              # claim work
bd create --title="…" --description="…" --type=task|bug|feature|epic --priority=P2
bd dep add <id> <depends-on>        # <id> depends on <depends-on>
bd close <id> [<id> …]              # complete (space-separate to batch)
bd search <query>                   # find by keyword
```

- Add **`--json`** to read commands for machine-readable output.
- `bd ready` / `bd list` truncate (100 / 50 rows) — pass **`--limit 0`** for an unbounded list.
- Priority is `0`–`4` / `P0`–`P4` (0 = critical, 2 = medium, 4 = backlog) — never "high/medium/low".

## Gotchas worth knowing

- **`--notes` / `--description` / `--acceptance` overwrite the entire field.** To add
  without clobbering, use **`--append-notes`**. Replace-variants are for initial write
  or deliberate overwrite only.
- **`bd … --json` shapes that trip `jq`:**
    - `bd show <id> --json` is a single-element **array** — index `.[0]`.
    - Multi-line fields (`notes` / `description` / `acceptance`) carry literal newlines
      `jq` rejects — read them with Python, not `jq`.
    - `.dependencies[]` (in `bd show --json`) is the **full target bead** plus a
      `.dependency_type` field, not a lean edge:
      `.[0].dependencies | map({id, type: .dependency_type})`.
    - `bd label list <id> --json` is a **flat array of strings** — `jq 'index("foo")'`,
      not `.labels | index(...)`.
    - `bd dep list <id> --direction up|down --json` → `{id, dependency_type, status}`
      where `.id` is the bead at the *other* end of the edge.
- **`blocks` has a type wall:** epics block only epics, non-epics block only non-epics —
  cross-type is a hard error. For a soft task→epic link use `--type related-to`.
- **`bd create --parent <id>` auto-creates the dependency edge** — don't also
  `bd dep add <child> <parent>`; bd rejects it as a deadlock.
- **`bd create` is pure capture** — filing a bead is not starting it. Reserve
  "Starting work on <id>…" for when the user explicitly directs work on a specific bead.

## Session close — work isn't done until it's pushed

```bash
git pull --rebase
bd dolt push          # sync beads to the Dolt remote
git push
git status            # must read "up to date with origin"
```

If a push fails, resolve and retry — never leave work stranded locally.
