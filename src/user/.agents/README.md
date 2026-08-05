# src/user/.agents/ — Shared Content

Tool-agnostic content that `scripts/install.sh` copies into **every detected
AI coding assistant** (Claude Code, Codex CLI, Gemini CLI, OpenCode). If
something here is useful to more than one tool, it lives here.

## What lives here

- `USER-CORE.md.template` — the zero-based shared laws, decision matrix, hard
  lines, and conventions (D17). Every tool's instruction template pulls this in
  with a `DYNAMIC-INCLUDE` marker, so it is the one file whose text reaches all
  four tools verbatim. It is currently hand-deployed to the standard homes;
  `agents-config-9k9.10` tracks wiring it into automated per-tool assembly.
- `skills/` — methodology guides, one directory per skill with a `SKILL.md` and
  optional supporting scripts.
- `rules/` — tool-agnostic always-on rules. Empty today: every rule here was
  record-less and was retired out of the repository.

`skills/` and `rules/` are gated on admission: a file without a complete
`admission:` record in its front matter is dropped at deploy and pruned from
every tool's config. Readmission is an explicit act, not a `git mv` back. An
admitted artifact can still fail a mechanical staging check and deploy nothing,
so confirm against the tool's own config directory rather than assuming.

## Where it installs

Into every detected tool's config directory — Claude Code `~/.claude/`, Codex
CLI `~/.codex/`, Gemini CLI `~/.gemini/`, OpenCode `~/.config/opencode/`.
Skills land under `<config>/skills/`, rules under `<config>/rules/`, and the
instruction text is assembled into each tool's own instruction file.

The installer strips the `.template` suffix on copy and skips tools that aren't
detected on the system.

## Who it's for

Fork-and-install users who want a ready-made set of skills and shared
instruction text to drop into their `~/.<tool>/` config. Not a library for
programmatic consumption — these are prose files meant to be read by an LLM at
runtime.

See the [root README](../../../README.md) for install flow and customization
pointers. Do not duplicate install instructions here.
