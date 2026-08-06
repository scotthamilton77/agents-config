# Reference

**This page is not written yet.** It previously held cheat-sheet tables — skills
by phase, agents, commands, rules, gates, configuration keys — for the harness as
it stood before the current rebuild. Almost none of those entries survived the
rebuild, so the tables have been removed rather than left to mislead you. For
what the rebuild is doing and why, read
[`docs/specs/2026-07-21-harness-rework-way-forward.md`](../specs/2026-07-21-harness-rework-way-forward.md).

Until then, the source tree is the authoritative list of what ships:
`src/user/.agents/skills/` for skills installed to every tool,
`src/user/.claude/skills/` and `src/user/.claude/commands/` for Claude-only
skills and slash commands, and the `rules/` directory alongside each. Anything
whose front matter lacks a complete admission record is dropped at install, so
the directory is the upper bound on what you get, not a guarantee.

A reference can only be written once the surface it describes stops moving. Four
pieces of the rebuild are still open, and each one decides entries this page
would have to carry:

- **The review contracts** — the verdict schema and the review roles that
  replace the old completion-gate tables.
- **The scaffold pipeline** — what replaces the retired planning and test-first
  skills in the implementation phase.
- **The PR-grooming carve** — which delivery and merge-eligibility behaviour
  survives, and in what form.
- **The executor loop** — the run loop that ties the phases together; today the
  pieces exist without a driver.

The charter lists these in the order they are being built.

When those land, this page gets written against what actually deploys. In the
meantime, [The SDLC Workflow](./sdlc-workflow.md) marks each phase with whether
it has a deployed implementation.
