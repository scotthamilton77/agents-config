# Delivery (beads-aware addendum)

Terminology: a **formula** is an authoring-time TOML template under `.beads/formulas/`; a **molecule** is its runtime instantiation (via `bd mol pour` or `bd mol wisp`). At implementation time you drive the molecule — refer to its "current step", not to the formula.

For bead-tracked work, delivery runs inside molecule steps, not as a peer workflow. The formulas below show which step of each molecule owns delivery:

- `implement-feature` (defined in `implement-feature.formula.toml`) — the `create-pr` step invokes `superpowers:finishing-a-development-branch`; the `await-review` step invokes `superpowers:wait-for-pr-comments`, which internally chains to `superpowers:reply-and-resolve-pr-threads` for thread reply + resolve (no separate molecule step needed).
- `fix-bug` — same pattern: `create-pr` → `superpowers:finishing-a-development-branch`, `await-review` → `superpowers:wait-for-pr-comments` (internally chains to `superpowers:reply-and-resolve-pr-threads`).
- `merge-and-cleanup` — runs after explicit user authorization; handles the merge itself.

**Do NOT** invoke `superpowers:finishing-a-development-branch`, `superpowers:wait-for-pr-comments`, or `superpowers:reply-and-resolve-pr-threads` as peers of the bead workflow — they run INSIDE the current molecule step (or via Skill A's internal chain to Skill B).

When the molecule's current step is `create-pr`, execute it immediately — the AUTOMATIC category in core `delivery.md` applies.

If you arrive at the end of a molecule step and are uncertain whether delivery has run, check via `bd show <bead-id>` and `bd mol current <mol-id>` — the molecule's next step drives the action, not your judgment.
