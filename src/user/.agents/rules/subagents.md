# Subagents

Rules for dispatching and managing subagents.

- After subagent work completes, verify worktree cleanup and branch locks before proceeding — orphaned worktrees block future `git worktree add` calls with the same name and stale branch locks block subsequent checkouts.
- Do not send messages to already-terminated ephemeral agents — check agent status first; sending to terminated agents causes silent no-ops or harness errors that look like successful dispatches.
