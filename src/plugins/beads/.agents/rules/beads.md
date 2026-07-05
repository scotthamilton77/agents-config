# Beads CLI

- A bead's parent is the dependency edge, not its dotted ID. There is no deferred/hidden state — `bd close` is the only way to remove a bead from active queues.
- `bd list` truncates at 50 by default; a bead not in the list may simply be past the limit, not closed. Always `bd show <id>` for authoritative state.
- `bd dolt pull` fails with "cannot merge with uncommitted changes." Sync via `bd dolt commit` then `bd dolt push` — a successful push proves you were not behind.
- `bd label remove` signature: `[issue-ids...] [label]` — label is the last arg, one label per call.
- After `bd close <last-child>`, always `bd show <parent-epic>` to confirm; close-walk auto-close is unreliable. Close the epic manually if all children are closed and it is still open.
- A bead's `in_progress` status is a claim lease — the work belongs to a live session for the current phase. Release it (`bd update <id> --status open`) or deliver it before the session ends, never abandon a claimed bead behind a merged spec or PR. `bd ready` surfaces only `open` beads, so a stale claim hides the work from every dispatch queue.
- Containers exit the planning queue only via the explicit `planned` label, which is revocable — re-planning removes it. Child count never implies `planned`.
