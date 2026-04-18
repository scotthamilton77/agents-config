# Worktrees

All git worktrees **must** be created inside `<project-root>/.claude/worktrees/` — that is, the `.claude/` directory at the root of the repository, not nested inside any subdirectory.

- **Preferred:** Use Claude Code's native `EnterWorktree` tool — it places worktrees here automatically
- **Manual:** `git worktree add .claude/worktrees/<name> -b <branch>` (run from the project root)

**Override:** The superpowers `using-git-worktrees` skill defaults to `.worktrees/` at the project root. Disregard that default — `<project-root>/.claude/worktrees/` is the required location regardless of what any skill specifies.
