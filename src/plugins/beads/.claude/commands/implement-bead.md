# Implement Bead

Implement a bead (issue) end-to-end: understand it, build it with TDD, verify it, and review it.

## Step 0 — Resolve the Bead

`$ARGUMENTS` is either a bead ID or a text description.

- If it looks like an ID (e.g. `feat-42`, `bug-7`): run `bd show $ARGUMENTS`
- Otherwise: run `bd search "$ARGUMENTS"` to find candidates
- If multiple matches: present the list and ask the user to pick one
- If no matches: stop and tell the user — do not guess

Once resolved, read the bead fully. Note its acceptance criteria, dependencies, and any linked parent/epic. Mark it `in_progress` with `bd update <id> --status=in_progress`. If it has a parent, mark the parent `in_progress` too.

## Step 1 — Understand the Scope

Read all files referenced in the bead description. Then determine:

1. **Project type**: Is this a monorepo (has `pnpm-workspace.yaml`, `lerna.json`, `workspaces` in `package.json`, or multiple `package.json` files) or a single-package project?
2. **Affected areas**: Which packages/directories need changes?
3. **Dependencies between areas**: Can work units proceed independently, or do some depend on others?

If anything in the bead is ambiguous or contradictory, stop and ask the user before proceeding.

## Step 2 — Implement with TDD

Invoke the `test-driven-development` skill for all implementation work.

**If multiple independent work units exist** (e.g. separate packages in a monorepo): invoke the `dispatching-parallel-agents` skill to run them in parallel. Each parallel unit must:
1. Write failing tests first based on the bead requirements
2. Implement until those tests pass
3. Fix any lint/type errors within its scope

**If only one work unit** (single package or tightly coupled changes): work through it sequentially using TDD.

If any unit fails and you cannot resolve it, stop the entire process and report what went wrong. Do not guess at fixes across unit boundaries.

## Step 3 — Integration Verification

Invoke the `verification-before-completion` skill. At minimum:

1. Run the full test suite (not just changed tests)
2. Run the type checker
3. Run the linter
4. Fix any integration failures discovered

Do not proceed until all checks pass clean.

## Step 4 — Code Review & Simplification

1. Invoke the `code-reviewer` agent on all changed files
2. Invoke the `code-simplifier` agent on all changed files
3. **Auto-fix** any findings rated critical or important
4. If auto-fixes were made, re-run verification (Step 3)

## Step 5 — Report to User

Present a summary:
- What was implemented and where
- Tests added/modified
- Any remaining code review findings that were not auto-fixed (with severity and description)
- Current bead status

Then ask the user what they'd like to do next (e.g. commit, close the bead, address remaining findings, adjust something).