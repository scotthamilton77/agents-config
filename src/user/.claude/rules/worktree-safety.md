# Worktree Safety

- Verify isolation by path (`git rev-parse --show-toplevel` contains `.claude/worktrees/`), not just branch name — the branch can be right while the main folder gets switched.
- `Write`/`Edit` act on absolute paths, not shell cwd — build every file path under the worktree root, never the main repo root.
- Subagents inherit the orchestrator's cwd at spawn. For isolated parallel workers: orchestrator `EnterWorktree` → spawn subagent (no isolation arg) → `ExitWorktree` (keep, don't remove) → repeat.
- `Agent(isolation: "worktree")` is silently ignored for named/team agents — don't rely on it.
- Before `EnterWorktree`, run an unscoped `git status` in the main tree — unstaged files and deletions don't carry into the new worktree.
- Never `git worktree remove` a worktree while a subagent occupies it — writes go non-deterministic (phantom-cwd via stale inode).
- After a subagent finishes, confirm its worktree is cleaned up and no stale branch lock remains — an orphaned worktree blocks a future `git worktree add` of the same name; a stale lock blocks checkouts.
