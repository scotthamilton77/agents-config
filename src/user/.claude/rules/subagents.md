# Subagents

Rules for dispatching and managing subagents.

- After subagent work completes, verify worktree cleanup and branch locks before proceeding.
- Do not send messages to already-terminated ephemeral agents — check agent status first.
