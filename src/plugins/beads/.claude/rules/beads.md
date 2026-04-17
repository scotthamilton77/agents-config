# Beads

Task tracking workflow (run with `dangerouslyDisableSandbox: true`).

`bd <command> [args]` — Types: bug | feature | task | epic | chore
Priority: 0-4 / P0-P4 (0=critical, 2=medium, 4=backlog). NOT "high"/"medium"/"low".

**Workflow**: `bd ready` → `bd update <id> --status=in_progress` → `bd close <id>` → `bd sync`

**Rules**:
- Use bd for ALL tracking, `--json` for programmatic use
- No markdown TODO lists unless user explicitly requests
- Discovered work → new bead with `discovered-from:<parent-id>` dep, don't fix inline
- Acceptance criteria: "Build passes. Typecheck passes. Tests pass."
- Epic children parallel by default — only explicit deps create sequence
- For bead-tracked work, specs may be written directly into the bead description (`bd update <id> --description "..."`) — the bead is the plan file

**Parent/child workflow** (you forget this):
- Claiming child → mark parent `in_progress` too
- Before work → `bd show <parent-id>` for acceptance criteria and siblings
- Before user review → run completion gate pipeline
- After close → if all siblings closed, close parent recursively
