# GitHub CLI Gotchas

- `gh api .../pulls/N/comments` silently truncates at the first page; always pass `--paginate` when verifying recent activity or specific reply IDs.
- `gh pr merge` may exit 0 while printing a rejection message; always verify with `gh pr view <n> --json state` — expected value `"MERGED"`.
- Remove the local git worktree before `gh pr merge --delete-branch`; the API merge succeeds but local branch deletion fails when a worktree has it checked out.
