# Subagents

- After subagent work completes, verify worktree cleanup and branch locks before proceeding — orphaned worktrees block a future `git worktree add` of the same name; stale branch locks block subsequent checkouts.
- Do not message already-terminated ephemeral agents — check status first; sends to terminated agents silently no-op or raise harness errors that look like successful dispatches.
- Treat reviewer-subagent findings (`quality-reviewer`, `simplify`) as signal, not gospel — they run with zero project context and apply generic heuristics. Before acting on a finding that mutates a project convention (a `.gitignore` add, a rename, a config consolidation), verify ground truth first (`git ls-files`, `find`, nearby conventions files): a blanket change can shadow a deliberate per-directory rule and silently un-track intentionally-versioned files.
