# Subagents

Rules for dispatching and managing subagents.

- After subagent work completes, verify worktree cleanup and branch locks before proceeding — orphaned worktrees block future `git worktree add` calls with the same name and stale branch locks block subsequent checkouts.
- Do not send messages to already-terminated ephemeral agents — check agent status first; sending to terminated agents causes silent no-ops or harness errors that look like successful dispatches.
- Treat reviewer-subagent findings as signal, not gospel — agents like `quality-reviewer` and `simplify` run with zero project context and apply generic best-practice heuristics. Before acting on a finding that mutates project conventions (e.g. "add `<pattern>` to `.gitignore`", "rename `<file>` for consistency", "consolidate these two configs"), verify the actual project convention with the tools that show ground truth: `git ls-files | grep <pattern>`, `find . -name <basename>`, or reading nearby conventions files. A blanket `.gitignore` addition can shadow a deliberate per-directory rule and silently un-track files that the project intentionally versions.
