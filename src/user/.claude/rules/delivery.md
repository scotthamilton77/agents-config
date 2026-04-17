# Delivery

Implements shared `<verification-checklist>` steps 6–8 with Claude-specific tools.

After completion gate passes for non-trivial work:

1. `using-git-worktrees` skill — isolate work if not already in a worktree (checklist step 6)
2. `finishing-a-development-branch` skill — create PR, push branch (checklist step 7)
3. `wait-for-pr-comments` skill — **mandatory, not optional**; monitor for Copilot review, triage feedback (checklist step 8)

Housekeeping (checklist steps 9–10) applies throughout: record discovered work, update memory.

**Merge prohibition**: Creating a PR is NOT authorization to merge. Do NOT merge without explicit user authorization in this session. Authorized phrases: "go ahead and merge", "merge it", "ship it". When in doubt, the user has not authorized it.

**PR comments**: Check for BOTH top-level AND inline review comments (e.g., Copilot inline suggestions) before marking a PR as review-complete. Inline comments are easy to miss—always run both commands:
```
gh pr view <PR> --comments
gh api repos/{owner}/{repo}/pulls/{pr}/comments
```

Do NOT merge or clean up worktrees/branches until Copilot review completes or times out.

**PR comments**: Check for BOTH top-level AND inline review comments (e.g., Copilot inline suggestions) before marking a PR as review-complete. Inline comments are easy to miss—always verify both.
