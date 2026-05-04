# implement-bead

Invoke the implement-bead skill for the given bead ID.

This slash command is the entry point for the shell driver's per-stage
`claude -p` invocation. It takes a single argument — the bead ID — and
hands off to the implement-bead skill, which reads the appropriate stage
step-bead, dispatches subagents/skills per the stage spec, persists
state-out to bd/filesystem, and exits.

## Invocation

```
/implement-bead <bead-id>
```

Arguments: `$ARGUMENTS` receives the bead ID (e.g. `proj-42`).

## Behavior

1. Parse `$ARGUMENTS` as the bead ID.
2. Invoke the `implement-bead` skill with that bead ID.
3. The skill drives ONE stage of the bead's active molecule and exits.

## Supported invocation contexts

- **Interactive Claude session** — skill is discovered via the normal
  skill-lookup path; the session is interactive.
- **Shell driver `claude -p`** — the driver spawns `claude -p --session-id
  <uuidv5> "/implement-bead <bead-id>"` from the stage's cwd. Claude Code
  resolves this project-scoped slash command by walking up from cwd to find
  the `.claude/` directory containing this file.

## Slash-command resolution from worktrees

Claude Code resolves project-scoped commands by walking up from cwd to the
nearest `.claude/` directory. Because worktrees are full git checkouts, each
worktree contains a copy of this file and resolution succeeds from any
subdirectory of the worktree without additional configuration.

## Notes

- The driver sets cwd before spawning each `claude -p` invocation per the
  cwd contract in the architecture spec (section 5.4).
- The `--session-id` (UUIDv5 from namespace + `<bead-id>:<stage-role>`) enables
  transparent resumption if the process is killed and restarted.
- This command is a thin wrapper. All orchestration logic lives in the
  implement-bead skill.
