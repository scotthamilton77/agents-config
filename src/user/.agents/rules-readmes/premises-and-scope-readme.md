# Premises and Scope — Context

## Absence is not a state

`bd list` truncates at 50 by default; a bead not in the list may simply be past the limit, not closed. Always `bd show <id>` for authoritative state. Same pattern applies to `gh api` without `--paginate` and any other paginated CLI.

## Premise collapse exit

When a sub-design proposes "invert X to use model Y," read the cited architecture documents before exploring design options. If the premise collapses (e.g. the architecture it assumed doesn't exist or works the opposite way), surface that as the brainstorm's first finding and exit with a rejection rationale instead of spending a session designing the rework.

## Census before estimate

Opening sections of a doc or codebase are often atypical (already clean, already converted). Run `grep -c <target-pattern> <file>` for each key signal before stating a number.
