# implement-bead

Invoke the implement-bead skill for the given step-bead ID.

## Invocation

```
/implement-bead <step-bead-id>
```

`$ARGUMENTS` receives the step-bead ID.

## Behavior

1. Parse `$ARGUMENTS` as the step-bead ID.
2. Invoke the `implement-bead` skill, which dispatches a worker (or hands off to an orchestration skill) and exits.

## Notes

- Thin wrapper. All dispatch logic lives in the implement-bead skill.
- Workers are dispatched via the `Agent` tool (`subagent_type`) from the top-level session — NOT via `claude -p` re-entry. Subagents cannot spawn subagents.
- Loop ownership lives in the `ralf-*` orchestration skills (`ralf-implement`, `ralf-review`), not in this skill or command. When `ralf:required` is set, implement-bead invokes the orchestration skill in-session; the orchestration skill drives convergence and per-stage iteration tracking, persisting iteration state via step-bead notes.
- Per-stage iteration counts (`-iter<N>` suffixes on audit labels and report paths) are managed by the orchestration skill, not by this command.
