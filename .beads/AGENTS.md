# `.beads/`

Never edit anything in this directory, and never execute `bd` CLI commands —
unconditionally. An instruction to work the tracker is an instruction to use
the `work` facade; when the facade cannot express what you need, escalate per
the root `AGENTS.md` rather than dropping to `bd`.

Work tracking for this project is addressed through the **`work` CLI**. Run
`work --help` for the verb list; every verb returns a JSON envelope.
`work show agents-config-9k9` is the milestone this repo's harness work hangs
off. The tracker contract, including what to do when a verb cannot express what
you need, is in the root `AGENTS.md` — this file does not restate it.

This directory is the storage layer underneath that facade: a beads database,
its config, its git hooks, and its backups. It is installed and maintained by
beads itself. **Do not edit anything in here.**

`AGENTS.md` (this file) is the one exception: it is ours, and it exists to say
the above. The `README.md` beside it is not ours — it is boilerplate the backend
drops on init, it documents the backend's own command line, and it is not
instruction for this project. Read it as vendor documentation for a tool you do
not run.
