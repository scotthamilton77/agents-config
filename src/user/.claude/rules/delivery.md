# Delivery

Implements shared `<verification-checklist>` steps 6–8 with Claude-specific tools.

After completion gate passes for non-trivial work:

1. `using-git-worktrees` skill — isolate work if not already in a worktree (checklist step 6)
2. `finishing-a-development-branch` skill — create PR, push branch (checklist step 7)
3. `wait-for-pr-comments` skill — **mandatory, not optional**; monitor for Copilot review, classify each comment as FIX/SKIP/ESCALATE, fix all FIX items via per-comment subagents (or recognize as already-addressed), push combined commits, then by default invoke `reply-and-resolve-pr-threads` for thread reply + resolve (checklist step 8)

Housekeeping (checklist steps 9–10) applies throughout: record discovered work, update memory.

## Action Categories

**AUTOMATIC — execute without user authorization:**

- Create worktree
- Commit on feature branch
- Push feature branch
- Create PR
- Invoke `wait-for-pr-comments` (which by default chains to `reply-and-resolve-pr-threads` for thread reply + resolve)
- Address PR review feedback (classify, fix, push, reply, resolve threads)

**REQUIRES EXPLICIT AUTHORIZATION:**

- Merging a PR (authorized phrases: "go ahead and merge", "merge it", "ship it")
- Force-pushing
- Destructive git operations (`reset --hard`, `clean -fd`, `branch -D`)
- Pushing directly to main/master

Creating a PR is NOT authorization to merge. But PR creation itself is AUTOMATIC — **do not pause for it**. Pause only at the merge step.

**Red flag**: "Ready when you are" / "ready for delivery" / "awaiting your go-ahead" BEFORE PR creation → STOP. Delivery is automatic. Execute `finishing-a-development-branch` now. Only pause AT the merge step. When in doubt at the merge step, the user has not authorized it.

## PR comments

Check for BOTH top-level AND inline review comments (e.g., Copilot inline suggestions) before marking a PR as review-complete. Inline comments are easy to miss — always run both commands:

```
gh pr view <pr> --comments
gh api repos/<owner>/<repo>/pulls/<pr>/comments
```

Do NOT merge or clean up worktrees/branches until Copilot review completes or times out.
