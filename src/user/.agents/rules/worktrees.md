# Worktrees

Create worktrees in your native worktree tool's preferred location, or — absent such a tool — in `<repo-root>/.worktrees/`. Never nest them deeper in a subdirectory.

- No native tool: `git worktree add .worktrees/<name> -b <branch>` from the repo root.
- Agents collaborate on one workspace, so know the per-agent convention to find and enter each other's worktrees: Claude Code uses `<repo-root>/.claude/worktrees/` (via its native tool); every other agent uses `<repo-root>/.worktrees/`.
- Post-merge cleanup: run from the main repo root, never inside the worktree. After a squash-merge git reads the branch as unmerged — use `git branch -D`, and remove the worktree only once the work is confirmed on main.
