# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Project Purpose

This is a versioned collection of agents, skills, commands, and templates for AI coding assistants. The primary content is markdown files intended to be copied to `~/.claude/` (user-level) or `.claude/` (project-level) directories.

## Prerequisites (Plugins)

This configuration assumes the following Claude Code plugins are installed:

- **[obra/superpowers](https://github.com/obra/superpowers)** - Provides skills referenced throughout the templates: brainstorming, TDD, verification-before-completion, dispatching-parallel-agents, writing-plans, code-reviewer, code-simplifier, and others
- **[steveyegge/beads](https://github.com/steveyegge/beads)** - Git-backed issue tracker providing the `bd` command used in the `<beads>` section of the AGENTS.md template

## Repository Structure

- `scripts/` - Installation and maintenance scripts
  - `install.sh` - Syncs `src/user/.claude/` into `~/.claude/` with intelligent merge
- `docs/plans/` - Design documents for features in development
- `src/user/.claude/` - User-level config (copies to `~/.claude/`)
  - `agents/` - Role-based agent definitions (frontmatter + instructions)
  - `skills/` - Methodology guides, some with supporting code/scripts
  - `commands/` - Slash command definitions
  - `AGENT-PERSONA.md.template` - Agent persona/personality template
  - `USER-PERSONA.md.template` - User persona template
  - `AGENTS.md.template` - Main user AGENTS.md template
  - `CLAUDE.md.template` - CLAUDE.md template (points to AGENTS.md)
  - `settings.json.template` - Permission presets and experimental features
  - `AGENTS.md` - Installation instructions for this folder

## File Formats

### Agent files (`agents/*.md`)

```yaml
---
name: agent-name
description: One-line description
model: sonnet | opus | haiku | inherit
color: purple | indigo | blue | green | yellow | orange | red
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

- No build system, tests, or linting - this is pure documentation
- Changes should follow existing formatting conventions in each file type
- Agent descriptions should include concrete usage examples in the frontmatter
- Skills should be opinionated and actionable, not generic advice
