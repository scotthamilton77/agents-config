# agents-config

Versioned collection of agents, skills, and commands for AI coding assistants. Currently supports Claude Code, with planned support for other AI assistants (Gemini, Codex, etc.).

## Prerequisites

This configuration relies on two Claude Code plugins being installed:

- **[obra/superpowers](https://github.com/obra/superpowers)** - Provides the skill/agent framework referenced throughout: brainstorming, TDD, verification-before-completion, dispatching-parallel-agents, code-reviewer, code-simplifier, finishing-a-development-branch, and more
- **[steveyegge/beads](https://github.com/steveyegge/beads)** - Git-backed issue tracker providing the `bd` command used for task tracking in the AGENTS.md template

Without these plugins, the `<orchestration>`, `<delegation>`, and `<beads>` sections of the AGENTS.md template will reference skills and commands that don't exist.

## What's Inside

```
scripts/
└── install.sh                 # Sync src/ into ~/.claude/ with merge logic
docs/
└── plans/                     # Design documents for features in development
src/
└── user/.claude/              # User-level config (→ ~/.claude/)
    ├── agents/                # Role-based agent definitions
    ├── commands/              # Slash commands
    ├── skills/                # Methodology guides with examples
    ├── AGENT-PERSONA.md.template   # Agent persona/personality
    ├── USER-PERSONA.md.template    # User persona
    ├── AGENTS.md.template          # Main user AGENTS.md
    ├── CLAUDE.md.template          # Points to AGENTS.md
    ├── CLAUDE.md                   # Points to AGENTS.md
    └── settings.json.template      # Permissions & experimental features
```

### Agents

Role-specific configurations that define expertise areas, behavioral patterns, and domain knowledge. Each agent includes:

- **Frontmatter**: name, description, usage examples, model hints
- **Role definition**: What the agent specializes in
- **Standards**: Domain-specific best practices
- **Boundaries**: What the agent should and shouldn't do

### Skills

Deep methodology guides for specific tasks. Unlike agents (which define *who*), skills define *how* to approach particular problems:

| Skill | Purpose |
|-------|---------|
| `bugfix` | Parallel debugging investigation with systematic root-cause analysis |
| `condition-based-waiting` | Replace flaky timeouts with condition polling |
| `optimize-agents-md` | Meta-skill for improving agent definitions |
| `root-cause-tracing` | Systematic debugging methodology |
| `self-improving-agent` | Persist lessons from user corrections as actionable rules |
| `testing-anti-patterns` | Common testing mistakes and how to avoid them |
| `writing-unit-tests` | Test behavior, not implementation; when to refuse testing untestable code |

### Commands

Slash commands that can be invoked directly:

- `/implement-bead <id-or-description>` - Implement a bead end-to-end with TDD, verification, and code review
- `/optimize-my-agent <path>` - Analyze and improve an agent definition file

### Templates

- `AGENTS.md.template` - Base instructions including persona references, laws, constraints, orchestration, delegation, and workflow
- `AGENT-PERSONA.md.template` - Agent personality and behavioral traits (referenced from AGENTS.md via `@AGENT-PERSONA.md`)
- `USER-PERSONA.md.template` - User description and interaction preferences (referenced from AGENTS.md via `@USER-PERSONA.md`)
- `CLAUDE.md.template` - Minimal file that points to AGENTS.md
- `settings.json.template` - Pre-configured permission allowlists and experimental features (agent teams)

> **Note:** The templates contain content specific to the author's setup:
> - The persona templates reflect personal interaction preferences
> - The `<beads>` section assumes use of [steveyegge/beads](https://github.com/steveyegge/beads) as a task tracker
> - The `<orchestration>` and `<delegation>` sections assume [obra/superpowers](https://github.com/obra/superpowers) skills are available
> - Various constraints have a TypeScript/Node.js bias
>
> You'll want to customize or remove these sections to match your own workflow.

## Installation

### Automated (recommended)

```bash
# Preview what will change
./scripts/install.sh --dry-run

# Install with confirmation prompts
./scripts/install.sh

# Install accepting all changes
./scripts/install.sh --yes
```

The install script:
- Copies `*.md.template` files to `~/.claude/` (stripping `.template` suffix), with diff preview and confirmation for existing files
- Syncs `agents/`, `skills/`, and `commands/` directories using hash comparison per item
- Union-merges `settings.json.template` into existing `settings.json` (preserves your values, adds new keys/entries)
- Creates timestamped backups before overwriting anything
- Warns about items in `~/.claude/` that aren't tracked in the project

Requires `jq` for JSON merging.

### Manual

```bash
# Copy agents, skills, commands
cp -r src/user/.claude/agents ~/.claude/
cp -r src/user/.claude/skills ~/.claude/
cp -r src/user/.claude/commands ~/.claude/

# Copy and customize templates
cp src/user/.claude/AGENTS.md.template ~/.claude/AGENTS.md
cp src/user/.claude/AGENT-PERSONA.md.template ~/.claude/AGENT-PERSONA.md
cp src/user/.claude/USER-PERSONA.md.template ~/.claude/USER-PERSONA.md
cp src/user/.claude/CLAUDE.md.template ~/.claude/CLAUDE.md
cp src/user/.claude/settings.json.template ~/.claude/settings.json
```

### Project-level (applies to specific project)

```bash
cd /path/to/your/project

# Copy what you need
cp -r /path/to/agents-config/src/user/.claude/agents .claude/
cp -r /path/to/agents-config/src/user/.claude/skills .claude/
```

### Customizing Templates

The `.template` files are starting points. After copying:

1. Edit `AGENT-PERSONA.md` and `USER-PERSONA.md` to reflect your preferences
2. Edit `AGENTS.md` to adjust laws, constraints, and workflow sections
3. Edit `settings.json` to match your permission needs
4. Keep `CLAUDE.md` as-is (it just points to `AGENTS.md`)

## Scope: User vs Project

Claude Code looks for configuration in multiple locations with the following precedence:

| Location | Scope | Use Case |
|----------|-------|----------|
| `~/.claude/` | User (global) | Personal preferences, agents you always want available |
| `.claude/` in project | Project | Project-specific agents, skills, and settings |

Project-level settings override user-level. Use user-level for your personal workflow; use project-level for team-shared configurations.

## Roadmap

### Under Consideration

- [ ] **Templatized extensions** - Selectable "extensions" (task tracker, language preferences) that can be applied during installation
- [ ] **Gemini support** - Equivalent configurations for Google's Gemini
- [ ] **Codex support** - Equivalent configurations for OpenAI's Codex
- [ ] **Update mechanism** - Pull latest versions without clobbering customizations
- [ ] **Selective install** - Choose which agents/skills to install
- [ ] **Agent marketplace** - Community-contributed agents and skills
- [ ] **Compatibility matrix** - Track which agents work with which AI assistants
- [ ] **Testing framework** - Validate agent behavior with example prompts

## Contributing

This is currently a personal configuration repository. If you find it useful and want to contribute agents or skills, open an issue to discuss.

## License

MIT - Use however you like.
