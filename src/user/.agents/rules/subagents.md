# Subagents

- Treat reviewer-subagent findings (`quality-reviewer`, `simplify`) as signal, not gospel — they run with zero project context on generic heuristics. Before acting on one that mutates a project convention (a `.gitignore` add, a rename, a config consolidation), verify ground truth first (`git ls-files`, `find`, nearby conventions files): a blanket change can shadow a deliberate per-directory rule and silently un-track intentionally-versioned files.
- Don't message an already-terminated ephemeral agent — check status first; a message to a dead agent silently no-ops or raises a harness error that looks like a successful dispatch.
