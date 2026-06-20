# Beads CLI

- A bead's parent is the dependency edge, not its dotted ID. There is no deferred/hidden state — `bd close` is the only way to remove a bead from active queues.
- `bd dolt pull` fails with "cannot merge with uncommitted changes." Sync via `bd dolt commit` then `bd dolt push` — a successful push proves you were not behind.
- `bd label remove` signature: `[issue-ids...] [label]` — label is the last arg, one label per call.
- After `bd close <last-child>`, always `bd show <parent-epic>` to confirm; close-walk auto-close is unreliable. Close the epic manually if all children are closed and it is still open.
