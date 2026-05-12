# /resolve-human-bead

Resolve a human-flagged bead by invoking the `resolve-human-bead` skill on
the target bead-id.

## Usage

```
/resolve-human-bead <bead-id>
```

`<bead-id>` may be:

- an HEP escalation bead (carries `human` + has an incoming `bd dep` from a
  non-closed source),
- an `[h]` follow-up bead (carries `human` + has `parent` set + title prefix
  `[Human verify]`),
- a merge-gate hand-off escalation bead (carries `human` + `merge-ready` +
  title prefix `[Merge gate]`), or
- a source bead with no `human` label of its own but with one or more open
  `human`-labeled blockers (source-bead pivot).

## Behavior

Invoke the `resolve-human-bead` skill on `$ARGUMENTS`. The skill detects
the bead's class via priority-ordered probes and applies the right
resolution primitive interactively, with explicit user confirmation on
destructive actions.

## No-op semantics (target has no human-related state)

If `$ARGUMENTS` has no `human` label AND has no open `human`-labeled
blocker, print the one-line message:

```
No human escalation found on <id>; nothing to resolve.
```

Then exit cleanly with zero exit code (exit 0). Do NOT auto-create a
human bead. Do NOT escalate. The no-op path is intentional: invoking
`/resolve-human-bead` on a bead without human-related state is not an
error condition — it's a fast-path no-op.

## See also

- The `resolve-human-bead` skill (this command's body).
- `docs/specs/bead-pipeline-architecture.md` §5.6 (HEP design).
- The HEP section of `src/plugins/beads/.claude/rules/beads.md`.
