# Graphify Discipline

Never run `graphify update .` from inside a git worktree and commit the result on a feature branch. The output is keyed to the cwd and non-portable; it floods the diff and breaks graphify for others. Run only from the main repo root; keep graphify-out off feature branches.
