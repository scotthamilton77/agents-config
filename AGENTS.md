# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Project Purpose

This is a versioned collection of agents, skills, commands, and templates for AI coding assistants. The primary content is markdown files intended to be copied to `~/.claude/` (user-level) or `.claude/` (project-level) directories.

## Repository Structure

- `src/user/.claude/` - User-level config (copies to `~/.claude/`)
  - `agents/` - Role-based agent definitions (frontmatter + instructions)
  - `skills/` - Methodology guides, some with supporting code/scripts
  - `commands/` - Slash command definitions
  - `*.template` - Templates users customize after copying
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
