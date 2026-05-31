# `.beads/` — maintenance notes

## `PRIME.md` is the project's `bd prime` output

`bd prime` emits `PRIME.md` **verbatim** for this repo (verified 1:1) — it fully
replaces bd's built-in prime text *and* suppresses the auto-injected bd-memory
dump. It loads at **every session start and before each compaction**, so every
line is a recurring token cost across all future conversations. Keep it ruthlessly
minimal.

When editing `PRIME.md`:

- Add only beads knowledge that is **high-frequency or error/data-loss-preventing**.
  Deep machinery (molecules, formulas, HEP, claim/close-walk, labels) belongs in
  skills or `archive/`, not here.
- Don't reproduce the command catalog — point to `bd --help` / `bd <cmd> --help`.
- Never tell readers to "run `bd prime` for more" — it's circular; `bd prime` emits
  this file.
- Say nothing about which memory system to use. Memory routing lives in the
  `memory-routing` rule; bd's own memory injection is already suppressed by this override.
