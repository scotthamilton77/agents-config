# Delivery

Implements shared `<verification-checklist>` steps 6–8 with Claude-specific tools.

After completion gate passes for non-trivial work:

1. `using-git-worktrees` skill — isolate work if not already in a worktree (checklist step 6)
2. `finishing-a-development-branch` skill — create PR, push branch (checklist step 7)
3. `wait-for-pr-comments` skill — monitor for Copilot review, triage feedback (checklist step 8)

Housekeeping (checklist steps 9–10) applies throughout: record discovered work, update memory.

Do NOT merge or clean up worktrees/branches until Copilot review completes or times out.
