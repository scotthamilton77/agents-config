# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Project Purpose

This is a versioned collection of agents, skills, commands, and templates for AI coding assistants. Supports **Claude Code**, **OpenAI Codex CLI**, and **Google Gemini CLI**. Shared content is installed to all detected tools; tool-specific content goes only where it belongs.

## Prerequisites (Plugins)

This configuration assumes the following Claude Code plugins are installed:

- **[obra/superpowers](https://github.com/obra/superpowers)** - Provides skills referenced throughout the templates: brainstorming, TDD, verification-before-completion, dispatching-parallel-agents, writing-plans, code-reviewer, code-simplifier, and others
- **[steveyegge/beads](https://github.com/steveyegge/beads)** - Git-backed issue tracker providing the `bd` command used in the `<beads>` section of the AGENTS.md template

## Repository Structure

- `scripts/` - Installation and maintenance scripts
  - `install.sh` - Multi-tool installer with auto-detection, `--dry-run`, `--tools=` override
- `docs/plans/` - Design documents for features in development
- `docs/specs/` - Design specifications for implemented features
- `src/user/.agents/` - **Shared content** (copied into all detected tools)
  - `agents/` - Role-based agent definitions (frontmatter + instructions)
  - `skills/` - Methodology guides, some with supporting code/scripts
  - `INSTRUCTIONS.md.template` - Shared laws, constraints, workflow, orchestration
  - `AGENT-PERSONA.md.template` - Agent persona/personality template
  - `USER-PERSONA.md.template` - User persona template
- `src/user/.claude/` - **Claude-specific** content (copies to `~/.claude/`)
  - `commands/` - Slash command definitions (`.md`)
  - `AGENTS.md.template` - Claude instruction file (refs shared + Claude extensions)
  - `CLAUDE.md.template` - Points to AGENTS.md
  - `CLAUDE-EXTENSIONS.md.template` - Claude-specific sections (delegation, beads, git)
  - `settings.json.template` - Permission presets and experimental features
- `src/user/.codex/` - **Codex-specific** content (copies to `~/.codex/`)
  - `AGENTS.md.template` - Codex instruction file (refs shared + Codex extensions)
  - `CODEX-EXTENSIONS.md.template` - Codex-specific sections (placeholder)
- `src/user/.gemini/` - **Gemini-specific** content (copies to `~/.gemini/`)
  - `GEMINI.md.template` - Gemini instruction file (refs shared + Gemini extensions)
  - `GEMINI-EXTENSIONS.md.template` - Gemini-specific sections (placeholder)

## File Formats

### Agent files (`agents/*.md`)

```yaml
---
name: agent-name
description: One-line description
model: sonnet | opus | haiku | inherit
color: purple | indigo | blue | green | yellow | orange | red | cyan | teal | pink
---
```

Followed by role definition, standards, and boundaries.

### Skill files (`skills/*/SKILL.md`)

```yaml
---
name: skill-name
description: When to use this skill
---
```

Followed by methodology, examples, and decision trees. Skills may include supporting files (`.ts`, `.sh`) in the same directory.

### Command files (`commands/*.md`)

Plain markdown with instructions. `$ARGUMENTS` placeholder receives user input.

## Development Notes

- **NEVER run `install.sh` automatically** — only the user runs the installer, and only when they explicitly say so
- No build system, tests, or linting - this is pure documentation
- Changes should follow existing formatting conventions in each file type
- Agent descriptions should include concrete usage examples in the frontmatter
- Skills should be opinionated and actionable, not generic advice
