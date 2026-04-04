# agents-config

Versioned collection of agents, skills, and commands for AI coding assistants. Supports **Claude Code**, **OpenAI Codex CLI**, and **Google Gemini CLI**. Shared content is installed to all detected tools; tool-specific content goes only where it belongs.

## Prerequisites

This configuration relies on two Claude Code plugins being installed:

- **[obra/superpowers](https://github.com/obra/superpowers)** - Provides the skill/agent framework referenced throughout: brainstorming, TDD, verification-before-completion, dispatching-parallel-agents, code-reviewer, code-simplifier, finishing-a-development-branch, and more
- **[steveyegge/beads](https://github.com/steveyegge/beads)** - Git-backed issue tracker providing the `bd` command used for task tracking in the AGENTS.md template

Without these plugins, the `<orchestration>`, `<delegation>`, and `<beads>` sections of the AGENTS.md template will reference skills and commands that don't exist.

## What's Inside

```
scripts/
└── install.sh                      # Multi-tool installer with auto-detection
docs/
├── plans/                          # Design documents for features in development
└── specs/                          # Design specifications for implemented features
src/
└── user/
    ├── .agents/                    # Shared content (copied into all detected tools)
    │   ├── agents/                 # Role-based agent definitions
    │   ├── skills/                 # Methodology guides with examples
    │   ├── INSTRUCTIONS.md.template      # Shared laws, constraints, workflow
    │   ├── AGENT-PERSONA.md.template     # Agent persona/personality
    │   └── USER-PERSONA.md.template      # User persona
    ├── .claude/                    # Claude-specific (→ ~/.claude/)
    │   ├── commands/               # Slash commands
    │   ├── rules/                  # Workflow rules (delegation, completion-gate, delivery, git-commits, beads)
    │   ├── AGENTS.md.template      # Claude instruction file
    │   ├── CLAUDE.md.template      # Points to AGENTS.md
    │   ├── CLAUDE-EXTENSIONS.md.template  # Stub header (content moved to rules/)
    │   └── settings.json.template  # Permissions, hooks & experimental features
    ├── .codex/                     # Codex-specific (→ ~/.codex/)
    │   ├── AGENTS.md.template      # Codex instruction file
    │   └── CODEX-EXTENSIONS.md.template   # Codex-specific sections
    └── .gemini/                    # Gemini-specific (→ ~/.gemini/)
        ├── GEMINI.md.template      # Gemini instruction file
        └── GEMINI-EXTENSIONS.md.template  # Gemini-specific sections
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
| `merge-guard` | Pre-merge gate that blocks merging while automated reviews are pending or comments are unseen |
| `optimize-agents-md` | Meta-skill for improving agent definitions |
| `ralf-it` | Iterative refinement with fresh-eyes subagents that catch what the first pass missed |
| `root-cause-tracing` | Systematic debugging methodology |
| `self-improving-agent` | Persist lessons from user corrections as actionable rules |
| `test-review` | Code review of unit/integration tests for quality and design issues |
| `testing-anti-patterns` | Common testing mistakes and how to avoid them |
| `wait-for-pr-comments` | Copilot-aware PR review monitoring via background agents; auto-fix unambiguous feedback |
| `verify-checklist` | Structured completion auditing with evidence requirements |
| `writing-unit-tests` | Test behavior, not implementation; when to refuse testing untestable code |

### Commands

Slash commands that can be invoked directly:

- `/implement-bead <id-or-description>` - Implement a bead end-to-end with TDD, verification, and code review
- `/optimize-my-agent <path>` - Analyze and improve an agent definition file
- `/optimize-my-skill <path>` - Analyze and improve a skill definition
- `/refresh-agents-md` - Regenerate AGENTS.md from current repo state

### Templates

**Shared** (in `src/user/.agents/`):
- `INSTRUCTIONS.md.template` - Shared laws, constraints, workflow, and orchestration
- `AGENT-PERSONA.md.template` - Agent personality and behavioral traits (referenced via `@AGENT-PERSONA.md`)
- `USER-PERSONA.md.template` - User description and interaction preferences (referenced via `@USER-PERSONA.md`)

**Claude-specific** (in `src/user/.claude/`):
- `AGENTS.md.template` - Claude instruction file referencing shared content + Claude extensions
- `CLAUDE.md.template` - Minimal file that points to AGENTS.md
- `CLAUDE-EXTENSIONS.md.template` - Stub header (content moved to `rules/`)
- `settings.json.template` - Pre-configured permission allowlists, hooks, and experimental features

> **Note:** The templates contain content specific to the author's setup:
> - The persona templates reflect personal interaction preferences
> - The `<beads>` section assumes use of [steveyegge/beads](https://github.com/steveyegge/beads) as a task tracker
> - The `<orchestration>`, `<delegation>`, and `<delivery>` sections assume [obra/superpowers](https://github.com/obra/superpowers) skills are available
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
- Auto-detects installed tools (Claude Code, Codex CLI, Gemini CLI) or use `--tools=` to override
- Copies shared content (`src/user/.agents/`) into all detected tools
- Copies tool-specific content (e.g., `src/user/.claude/`) into the corresponding tool's config directory
- Copies `*.md.template` files (stripping `.template` suffix), with diff preview and confirmation for existing files
- Syncs `agents/`, `skills/`, and `commands/` directories using hash comparison per item
- Union-merges `settings.json.template` into existing `settings.json` (preserves your values, adds new keys/entries)
- Creates timestamped backups before overwriting anything
- Warns about items that aren't tracked in the project

Requires bash or zsh, plus `jq` for JSON merging. Use `--dry-run` to preview changes without writing.

### Manual

```bash
# Copy shared content (agents, skills)
cp -r src/user/.agents/agents ~/.claude/
cp -r src/user/.agents/skills ~/.claude/

# Copy Claude-specific content (commands)
cp -r src/user/.claude/commands ~/.claude/

# Copy and customize shared templates
cp src/user/.agents/INSTRUCTIONS.md.template ~/.claude/INSTRUCTIONS.md
cp src/user/.agents/AGENT-PERSONA.md.template ~/.claude/AGENT-PERSONA.md
cp src/user/.agents/USER-PERSONA.md.template ~/.claude/USER-PERSONA.md

# Copy and customize Claude-specific templates
cp src/user/.claude/AGENTS.md.template ~/.claude/AGENTS.md
cp src/user/.claude/CLAUDE.md.template ~/.claude/CLAUDE.md
cp src/user/.claude/CLAUDE-EXTENSIONS.md.template ~/.claude/CLAUDE-EXTENSIONS.md
cp src/user/.claude/settings.json.template ~/.claude/settings.json
```

### Project-level (applies to specific project)

```bash
cd /path/to/your/project

# Copy what you need
cp -r /path/to/agents-config/src/user/.agents/agents .claude/
cp -r /path/to/agents-config/src/user/.agents/skills .claude/
cp -r /path/to/agents-config/src/user/.claude/commands .claude/
```

### Customizing Templates

The `.template` files ship with the author's personal configuration and must be customized after installation.

**Must personalize** (these contain the author's identity):
1. **`USER-PERSONA.md`** — Replace entirely with your own name, role, and interaction preferences
2. **`AGENT-PERSONA.md`** — Defines the AI's personality and expertise claims. Adjust to your preferred style

**Adjust to your workflow:**
3. **`INSTRUCTIONS.md`** — Laws, constraints, workflow, and orchestration. The `<orchestration>` section references [superpowers](https://github.com/obra/superpowers) skills — remove or replace if not using that plugin
4. **Tool-specific extensions** — For Claude: workflow rules live in `rules/` (delegation, completion-gate, delivery, git-commits, beads). `<delegation>` and `<completion-gate>` reference superpowers skills; `<delivery>` wires worktree isolation, PR creation, and Copilot review monitoring; `<beads>` assumes [beads](https://github.com/steveyegge/beads). For Codex/Gemini: see `CODEX-EXTENSIONS.md` or `GEMINI-EXTENSIONS.md`. Remove sections for plugins you don't use
5. **`settings.json`** (Claude only) — Adjust permission allowlists, hooks, and deny rules to match your needs

**No changes needed:**
- `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` — Thin wrappers that reference the files above

## Scope: User vs Project

Claude Code looks for configuration in multiple locations with the following precedence:

| Location | Scope | Use Case |
|----------|-------|----------|
| `~/.claude/` | User (global) | Personal preferences, agents you always want available |
| `.claude/` in project | Project | Project-specific agents, skills, and settings |

Project-level settings override user-level. Use user-level for your personal workflow; use project-level for team-shared configurations.

## Roadmap

### Under Consideration

- [x] **Gemini support** - Equivalent configurations for Google's Gemini
- [x] **Codex support** - Equivalent configurations for OpenAI's Codex
- [ ] **Templatized extensions** - Selectable "extensions" (task tracker, language preferences) that can be applied during installation
- [ ] **Update mechanism** - Pull latest versions without clobbering customizations
- [ ] **Selective install** - Choose which agents/skills to install
- [ ] **Agent marketplace** - Community-contributed agents and skills
- [ ] **Compatibility matrix** - Track which agents work with which AI assistants
- [ ] **Testing framework** - Validate agent behavior with example prompts

## Contributing

This is currently a personal configuration repository. If you find it useful and want to contribute agents or skills, open an issue to discuss.

## License

MIT - Use however you like.
