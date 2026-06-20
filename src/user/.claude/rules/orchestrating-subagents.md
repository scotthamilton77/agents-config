# Orchestrating Subagents

When orchestrating subagents — dispatching workers, fanning out, or any case where a dispatched agent may itself spawn a subagent — use the `orchestrating-subagents` skill. A subagent cannot await a child it spawns (the child's completion wakes the root orchestrator, not the parent), so naive nesting stalls silently; the skill carries the coordination contract.
