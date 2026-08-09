# Contributing

This is currently a **personal configuration repository**. It reflects one
developer's workflow, personas, and tooling preferences. It's shared publicly
in case it's useful as a reference or starting point for your own setup.

## Before sending a PR

Please **open an issue first** to discuss the change. That keeps the scope
aligned with how the repo is actually used and avoids wasted work on PRs that
don't fit the project's direction.

Good reasons to open an issue:

- You spotted a bug in `scripts/install.sh` or a drift in the docs.
- You want to propose a new skill, agent, or command that has broad utility.
- You want to add support for another AI coding assistant alongside Claude
  Code, Codex CLI, Gemini CLI, and OpenCode.

Personal-taste changes (rewording personas, swapping opinions in skills,
changing the agent persona's personality) are usually better kept in your own
fork — that's what the templates are designed for.

## File format conventions

See [`AGENTS.md`](./AGENTS.md) for the file-format conventions used throughout
the repo:

- Agent files — frontmatter schema, documented in [`docs/primers/AGENTS_PRIMER.md`](./docs/primers/AGENTS_PRIMER.md). No agent definitions ship today and there is no `agents/` directory under `src/`, but `agents` is still a staged namespace, so the schema binds the first one added.
- Skill files — `SKILL.md` layout for `src/user/.agents/skills/*/`
- Command files — markdown layout for `src/user/.claude/commands/*.md`

## Install & plugin prerequisites

See the root [`README.md`](./README.md) for installation instructions and for
what the installed content actually depends on. Neither `obra/superpowers` nor
`steveyegge/beads` is a hard prerequisite: nothing installed today calls into
`superpowers`, and `beads` (via the `work` CLI, a facade over `bd`) is needed
only by five deployed skills — `to-tickets`, `wayfinder`,
`where-does-this-fit`, `triaging-discovered-work`, and `prototype` — each of
which degrades to its own fallback without it. See
[Getting Started](./docs/guide/getting-started.md#prerequisites) for what
each fallback is.
