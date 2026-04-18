# Worktrees

All git worktrees **must** be created inside `.claude/worktrees/`.

- **Preferred:** Use Claude Code's native `EnterWorktree` tool — it places worktrees here automatically
- **Manual:** `git worktree add .claude/worktrees/<name> -b <branch>`

**Override:** The superpowers `using-git-worktrees` skill defaults to `.worktrees/` at the project root. Disregard that default — `.claude/worktrees/` is the required location regardless of what any skill specifies.
