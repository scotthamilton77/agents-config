# Beads — Skills & Conventions

## Skill Pipeline

1. **`create-bead`** — capture placeholder (fast, no spec)
2. **`start-bead`** — route to brainstorm or implement based on readiness
3. **`implement-bead`** — pour formula, orchestrate subagents through DAG
4. **`run-queue`** — autonomous loop: find implementation-ready beads, process them

Formulas:
- `brainstorm-bead` — interactive spec writing + RALF spec review → `implementation-ready`
- `implement-feature` — label-driven (`ralf-implement` when `ralf:required`, else TDD + domain skills); hard-escalates on red tests; reroutes to `docs-only` when no test runner or no `[m]` AC lines
- `fix-bug` — root-cause diagnosis + same label-driven implementation; hard-escalate on red tests (Trigger A only)
- `docs-only` — single-pass, no test loop; verify-ac warn-and-passes when zero `[m]` ACs
- `merge-and-cleanup` — retroactive gate + explicit auth → merge

## Skill Partnership

- **Beads = OUTER lifecycle** — what work exists, its state, dependencies, multi-session persistence
- **Superpowers = INNER methodology** — how to do the work inside each molecule step

**Off-limits for bead-tracked work** (use bead lifecycle instead):
- `superpowers:writing-plans` — bead description IS the plan
- `superpowers:executing-plans` — `implement-bead` is the executor
- `superpowers:subagent-driven-development` — `implement-bead` orchestrates via formula DAG

All other superpowers skills are partners — use freely inside molecule steps.

## Notes vs Comments

| Command | Semantics | When to use |
|---|---|---|
| `bd update <id> --append-notes "..."` | Appends to notes | Step output, escalation context, run breadcrumbs |
| `bd update <id> --notes "..."` | **Replaces** notes entirely | Initial creation or intentional spec overwrites only |
| `bd comments add <id> "..."` | Non-destructive comment | Lifecycle audit, molecule→bead tracing |

**Footgun**: `--notes` is a destructive overwrite. Use `--append-notes` to add.
