# Worktree Safety

- Verify isolation by path (`git rev-parse --show-toplevel` contains `.claude/worktrees/`), not just branch name — the branch can be correct while the main folder gets switched.
- `Write`/`Edit` act on absolute paths, not shell cwd — build all file paths under the worktree root, never the main repo root.
- Subagents inherit the orchestrator's cwd at spawn. Pattern for isolated parallel workers: orchestrator `EnterWorktree` → spawn subagent (no isolation arg) → `ExitWorktree(keep)` → repeat.
- `Agent(isolation: "worktree")` is silently ignored for named/team agents. Do not rely on it.
- Before `EnterWorktree`, run an unscoped `git status` in the main tree — unstaged files and deletions do not carry over to the new worktree.
- Never `git worktree remove` a worktree while a subagent occupies it; writes become non-deterministic (phantom-cwd via stale inode).
