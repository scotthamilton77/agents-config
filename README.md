# agents-config

Versioned collection of agents, skills, and commands for AI coding assistants. Currently supports Claude Code, with planned support for other AI assistants (Gemini, Codex, etc.).

## What's Inside

```
src/
└── user/.claude/              # User-level config (→ ~/.claude/)
    ├── agents/                # Role-based agent definitions
    ├── commands/              # Slash commands
    ├── skills/                # Methodology guides with examples
    ├── AGENTS.md.template     # User AGENTS.md template
    ├── CLAUDE.md              # Points to AGENTS.md
    └── settings.json.template # Permission presets
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
| `writing-unit-tests` | Test behavior, not implementation; when to refuse testing untestable code |
| `testing-anti-patterns` | Common testing mistakes and how to avoid them |
| `root-cause-tracing` | Systematic debugging methodology |
| `condition-based-waiting` | Replace flaky timeouts with condition polling |
| `optimize-agents-md` | Meta-skill for improving agent definitions |

### Commands

Slash commands that can be invoked directly:

- `/optimize-my-agent <path>` - Analyze and improve an agent definition file

### Templates

- `AGENTS.md.template` - Base instructions including persona, interaction rules, and development workflow
- `CLAUDE.md` - Minimal file that points to AGENTS.md (following the new pattern)
- `settings.json.template` - Pre-configured permission allowlists for common tools

> **Note:** The `AGENTS.md.template` contains content specific to the author's setup:
> - The `<persona>` section reflects personal interaction preferences
> - The `<beads>` section assumes use of [beads](https://github.com/anthropics/claude-code/tree/main/packages/beads) as a task tracker
> - Various constraints have a TypeScript/Node.js bias
>
> You'll want to customize or remove these sections to match your own workflow.

## Installation (Manual)

Until automated install is available, copy files manually:

### User-level (applies to all projects)

```bash
# Copy agents
cp -r src/user/.claude/agents ~/.claude/

# Copy skills
cp -r src/user/.claude/skills ~/.claude/

# Copy commands
cp -r src/user/.claude/commands ~/.claude/

# Copy and customize templates
cp src/user/.claude/AGENTS.md.template ~/.claude/AGENTS.md
cp src/user/.claude/CLAUDE.md ~/.claude/
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

1. Edit `AGENTS.md` to reflect your preferences and persona
2. Edit `settings.json` to match your permission needs
3. Remove the `.template` suffix
4. Keep `CLAUDE.md` as-is (it just points to `AGENTS.md`)

## Scope: User vs Project

Claude Code looks for configuration in multiple locations with the following precedence:

| Location | Scope | Use Case |
|----------|-------|----------|
| `~/.claude/` | User (global) | Personal preferences, agents you always want available |
| `.claude/` in project | Project | Project-specific agents, skills, and settings |

Project-level settings override user-level. Use user-level for your personal workflow; use project-level for team-shared configurations.

## Roadmap

### In Progress

N/A

### Planned

- [ ] **Install/uninstall scripts** - Automated installation to user or project scope
- [ ] **Gemini support** - Equivalent configurations for Google's Gemini

### Under Consideration

- [ ] **Templatized extensions** - Extract author-specific sections (persona, task tracker, language preferences) from `AGENTS.md.template` into selectable "extensions" that can be applied during installation
- [ ] **Codex support** - Equivalent configurations for OpenAI's Codex
- [ ] **Update mechanism** - Pull latest versions without clobbering customizations
- [ ] **Conflict resolution** - Handle divergence between upstream and local modifications
- [ ] **Selective install** - Choose which agents/skills to install
- [ ] **Scope selection** - Install to user-level, project-level, or both
- [ ] **Validation** - Verify agent/skill files are well-formed before install
- [ ] **Diff preview** - Show what will change before applying updates
- [ ] **Agent marketplace** - Community-contributed agents and skills
- [ ] **Compatibility matrix** - Track which agents work with which AI assistants
- [ ] **Testing framework** - Validate agent behavior with example prompts

## Contributing

This is currently a personal configuration repository. If you find it useful and want to contribute agents or skills, open an issue to discuss.

## License

MIT - Use however you like.
