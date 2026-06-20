# Worktrees

All git worktrees **must** be created inside `<project-root>/.claude/worktrees/` — that is, the `.claude/` directory at the root of the repository, not nested inside any subdirectory.

- **Preferred:** Use the active assistant's native worktree tool when available (e.g., Claude Code's `EnterWorktree`) — it places worktrees here automatically
- **Manual:** `git worktree add .claude/worktrees/<name> -b <branch>` (run from the project root)

**Override:** The `using-git-worktrees` skill defaults to `.worktrees/` at the project root. Disregard that default — `<project-root>/.claude/worktrees/` is the required location regardless of what any skill specifies.

## Cleanup after merge

Run from the main repo root, never inside the worktree being removed. After a squash-merge both git and `ExitWorktree` read the branch as unmerged — use `git branch -D` (not `-d`), and pass `ExitWorktree` its `discard_changes: true` option, after confirming the work landed on main.
