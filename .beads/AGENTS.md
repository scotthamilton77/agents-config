# `.beads/`

Work tracking for this project is addressed through the **`work` CLI**, not
through `bd`. Run `work --help` for the verb list; every verb returns a JSON
envelope. `work show agents-config-9k9` is the milestone this repo's harness
work hangs off.

This directory is the storage and sync layer underneath that facade — a beads
database, its config, its git hooks, and its backups. It is installed and
maintained by beads itself. **Do not edit anything in here**, and do not reach
past `work` into `bd` to change tracker state.

`bd` remains the escape hatch for operations the facade cannot express. When
you use it, record what you needed and why as a note on `agents-config-9k9`, so
the gap becomes a facade change rather than a habit.

`AGENTS.md` (this file) is the one exception: it is ours, and it exists to say
the above.
