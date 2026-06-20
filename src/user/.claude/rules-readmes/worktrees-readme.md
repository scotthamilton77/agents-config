# Worktrees — Context

## Cleanup procedure

```bash
cd <repo-root>                               # never from inside the worktree
git worktree remove .claude/worktrees/<name>
git branch -D <branch>                       # -d fails after a squash-merge: branch reads as unmerged
git worktree list                            # verify: only main remains
```

`ExitWorktree` hits the same squash-merge trap — it sees the pre-squash commit as unmerged and refuses; pass `discard_changes: true` only after confirming the work is on main.
