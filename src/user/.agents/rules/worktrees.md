# Worktrees

Create all worktrees in `<repo-root>/.claude/worktrees/`, never nested in a subdirectory. This overrides the `using-git-worktrees` skill default of `.worktrees/`.

- Native tool (e.g. `EnterWorktree`) places them there automatically; manual: `git worktree add .claude/worktrees/<name> -b <branch>` from the repo root.
- Post-merge cleanup: run from the main repo root, never inside the worktree. After a squash-merge git reads the branch as unmerged — use `git branch -D` and pass `ExitWorktree` `discard_changes: true`, once the work is confirmed on main.
