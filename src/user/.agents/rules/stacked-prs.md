# Stacked PR Squash Merges

- GitHub retargets upper PRs only when the lower branch is deleted; without `--delete-branch`, manually run `gh pr edit N --base main`.
- Retargeted PRs conflict when lower-bead review-fixes landed in main's squash but not in the upper branch; resolve in-place with the three-way merge — do NOT `git checkout --ours`.
- Use `make ci-<pkg>` as the conflict-resolution oracle; green at coverage floor proves the resolution.
