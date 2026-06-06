# Worktrees

All git worktrees **must** be created inside `<project-root>/.claude/worktrees/` — that is, the `.claude/` directory at the root of the repository, not nested inside any subdirectory.

- **Preferred:** Use the active assistant's native worktree tool when available (e.g., Claude Code's `EnterWorktree`) — it places worktrees here automatically
- **Manual:** `git worktree add .claude/worktrees/<name> -b <branch>` (run from the project root)

**Override:** The `using-git-worktrees` skill defaults to `.worktrees/` at the project root. Disregard that default — `<project-root>/.claude/worktrees/` is the required location regardless of what any skill specifies.

## Worktree cleanup after merge

Run cleanup from the **main repo root**, never from inside the worktree being removed. After a squash-merge (GitHub default), git sees the local branch as unmerged — `git branch -d` always fails; use `git branch -D`. The same applies to `ExitWorktree`: after a squash-merge, the tool sees the pre-squash commit as unmerged and refuses — always pass `discard_changes: true` after confirming the work is on main.

```bash
cd <repo-root>
git worktree remove .claude/worktrees/<name>
git branch -D <branch>
# Verify:
git worktree list  # should show only main
```
