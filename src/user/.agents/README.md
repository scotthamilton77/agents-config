# src/user/.agents/ — Shared Content

Tool-agnostic content that `scripts/install.sh` copies into **every detected
AI coding assistant** (Claude Code, Codex CLI, Gemini CLI). If something here
is useful to more than one tool, it lives here.

## What lives here

- `agents/` — Role-based agent definitions (backend, frontend, reviewer, etc.).
  Each is a single `.md` file with YAML frontmatter followed by role,
  standards, and boundaries.
- `skills/` — Methodology guides, one directory per skill with a `SKILL.md`
  and optional supporting scripts.
- `AGENTS.md.template` — Zero-based shared laws, decision matrix, and hard
  lines referenced by each tool's top-level instruction file.
- `SESSION-PRIMER.md.template` — Skill-invocation discipline (the "1% rule"
  + red-flag rationalization table + skill-priority ordering). Dynamically
  included between USER-PERSONA and the shared AGENTS.md content in every
  per-tool template.
- `AGENT-PERSONA.md.template` — Agent personality and expertise claims.
  Personalize after install.
- `USER-PERSONA.md.template` — User description and interaction preferences.
  Personalize after install.

## Where it installs

Into every detected tool's config directory:

- Claude Code → `~/.claude/agents/`, `~/.claude/skills/`,
  `~/.claude/AGENTS.md`, etc.
- Codex CLI → `~/.codex/agents/`, `~/.codex/skills/`, `~/.codex/AGENTS.md`, etc.
- Gemini CLI → `~/.gemini/agents/`, `~/.gemini/skills/`, `~/.gemini/GEMINI.md`, etc.

The installer strips the `.template` suffix on copy and skips installing to
tools that aren't detected on the system.

## Who it's for

Fork-and-install users who want a ready-made set of agents, skills, and
persona templates to drop into their `~/.<tool>/` config. Not a library for
programmatic consumption — these are prose files meant to be read by an LLM
at runtime.

See the [root README](../../../README.md) for install flow and customization
pointers. Do not duplicate install instructions here.
