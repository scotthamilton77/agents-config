# Delivery (beads-aware addendum)

For bead-tracked work, delivery runs inside formula steps, not as a peer workflow.

- `implement-feature.formula.toml` — the `create-pr` step invokes `superpowers:finishing-a-development-branch`; the `await-review` step invokes `superpowers:wait-for-pr-comments`.
- `fix-bug.formula.toml` — same pattern: `create-pr` → `superpowers:finishing-a-development-branch`, `await-review` → `superpowers:wait-for-pr-comments`.
- `merge-and-cleanup.formula.toml` — runs after explicit user authorization; handles the merge itself.

**Do NOT** invoke `superpowers:finishing-a-development-branch` or `superpowers:wait-for-pr-comments` as peers of the bead workflow — they run INSIDE the formula step the molecule is currently on.

When the formula's current step is `create-pr`, execute it immediately — the AUTOMATIC category in core `delivery.md` applies.

If you arrive at the end of a formula step and are uncertain whether delivery has run, check via `bd show <bead-id>` and `bd mol current <mol-id>` — the molecule's next step drives the action, not your judgment.
