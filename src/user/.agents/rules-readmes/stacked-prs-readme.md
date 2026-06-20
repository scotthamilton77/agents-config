# Stacked PR Squash Merges — Context

## Why retargeted PRs conflict

Lower-bead review-fixes committed after the upper branch forked land in main's squash commit but not in the upper branch. The three-way merge sees main's fixed lines vs. the upper branch's stale lines → conflict markers. Fix in-place; do NOT `git checkout --ours <file>` — that drops auto-merged hunks of the lower fix.

## Oracle

Green `make ci-<pkg>` at the coverage floor proves the resolution is correct.

## Full procedure per upper PR (bottom-up)

```bash
gh pr edit N --base main
git merge origin/main           # in the bead's worktree
# resolve conflicts in editor — keep-ours for the bead's own evolved files
git add <resolved-files>        # MUST add — editing alone leaves status U
make ci-<pkg>                   # oracle
git commit --no-edit
git push
gh pr merge N --squash --admin
gh pr view N --json state       # verify "MERGED"
git show --stat origin/main     # confirm landed diff is scoped to this bead only
```
