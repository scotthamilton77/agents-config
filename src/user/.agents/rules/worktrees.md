# Worktrees

Create worktrees in your native worktree tool's preferred location, or — absent such a tool — in `<repo-root>/.worktrees/`. Never nest them deeper in a subdirectory.

- No native tool: `git worktree add .worktrees/<name> -b <branch>` from the repo root.
- Agents collaborate on one workspace, so know the per-agent convention to find and enter each other's worktrees: Claude Code uses `<repo-root>/.claude/worktrees/` (via its native tool); every other agent uses `<repo-root>/.worktrees/`.
- Post-merge cleanup: run from the main repo root, never inside the worktree. After a squash-merge git reads the branch as unmerged — use `git branch -D`, and remove the worktree only once the work is confirmed on main.
- One committer per worktree at a time. Never dispatch concurrent subagents that
  each commit into the same worktree — serialize them, or give each its own
  worktree. A shared index means `git add -A`/`commit -a` can swallow a sibling's
  in-flight files, and any post-commit HEAD read can return a sibling's commit.
- Capture your commit SHA from the commit itself, never from a later read. The
  `git commit` output banner (`[branch abc1234] ...`) is the only SHA that is
  provably yours; `git rev-parse HEAD` / `git log -1` after the fact report
  whatever landed last, which under concurrency may not be you. Before reporting
  a SHA, confirm it matches your own commit banner's short SHA and file stats.