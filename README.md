# agents-config

Versioned collection of agents, skills, and commands for AI coding assistants. Supports **Claude Code**, **OpenAI Codex CLI**, and **Google Gemini CLI**. Shared content is installed to all detected tools; tool-specific content goes only where it belongs.

## Prerequisites

This configuration relies on two Claude Code plugins being installed:

- **[obra/superpowers](https://github.com/obra/superpowers)** - Provides the skill/agent framework referenced throughout: brainstorming, TDD, verification-before-completion, dispatching-parallel-agents, code-reviewer, code-simplifier, finishing-a-development-branch, and more
- **[steveyegge/beads](https://github.com/steveyegge/beads)** - Git-backed issue tracker providing the `bd` command used for task tracking in the AGENTS.md template

Without these plugins, the shared `<orchestration>` section in `INSTRUCTIONS.md` and several Claude-specific workflow rules (`delegation`, `completion-gate`, `delivery` under `src/user/.claude/rules/`, and `beads` under `src/plugins/beads/`) will reference skills and commands that don't exist.

## What's Inside

```
scripts/
└── install.sh                      # Multi-tool installer with auto-detection
docs/
├── plans/                          # Design documents for features in development
└── specs/                          # Design specifications for implemented features
src/
├── user/
│   ├── .agents/                    # Shared content (copied into all detected tools)
│   │   ├── agents/                 # Role-based agent definitions
│   │   ├── skills/                 # Methodology guides with examples
│   │   ├── INSTRUCTIONS.md.template      # Shared laws, constraints, workflow
│   │   ├── AGENT-PERSONA.md.template     # Agent persona/personality
│   │   └── USER-PERSONA.md.template      # User persona
│   ├── .claude/                    # Claude-specific (→ ~/.claude/)
│   │   ├── commands/               # Slash commands
│   │   ├── rules/                  # Workflow rules (delegation, completion-gate, delivery, git-commits, codex-routing, subagents)
│   │   ├── AGENTS.md.template      # Claude instruction file
│   │   ├── CLAUDE.md.template      # Points to AGENTS.md
│   │   ├── CLAUDE-EXTENSIONS.md.template  # Stub header (content moved to rules/)
│   │   └── settings.json.template  # Permissions, hooks & experimental features
│   ├── .codex/                     # Codex-specific (→ ~/.codex/)
│   │   ├── AGENTS.md.template      # Codex instruction file
│   │   └── CODEX-EXTENSIONS.md.template   # Codex-specific sections
│   └── .gemini/                    # Gemini-specific (→ ~/.gemini/)
│       ├── GEMINI.md.template      # Gemini instruction file
│       └── GEMINI-EXTENSIONS.md.template  # Gemini-specific sections
└── plugins/                        # Optional plugin content (installed only when auto-detected)
    └── beads/                      # beads plugin: skills, Claude rules, formulas
```

### Agents

Role-specific configurations that define expertise areas, behavioral patterns, and domain knowledge. Each agent file has YAML frontmatter (name, description, model, color) followed by role definition, domain-specific standards, and boundaries. See [`src/user/.agents/agents/`](./src/user/.agents/agents/) for the full set.

Shipping agents:

- `api-developer`
- `backend-developer`
- `code-debugger`
- `code-documenter`
- `code-refactor`
- `code-reviewer`
- `data-scientist`
- `database-designer`
- `frontend-developer`
- `javascript-developer`
- `tech-lead`
- `typescript-developer`

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
| `verify-checklist` | Structured completion auditing with evidence requirements |
| `wait-for-pr-comments` | Copilot-aware PR review monitoring via background agents; auto-fix unambiguous feedback |
| `writing-unit-tests` | Test behavior, not implementation; when to refuse testing untestable code |

### Commands

Slash commands that can be invoked directly:

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
> - The `beads` plugin (under `src/plugins/beads/`) assumes use of [steveyegge/beads](https://github.com/steveyegge/beads) as a task tracker
> - The `<orchestration>` section (in `INSTRUCTIONS.md`) and the `delegation`, `completion-gate`, and `delivery` rules (in `src/user/.claude/rules/`) assume [obra/superpowers](https://github.com/obra/superpowers) skills are available
> - Various constraints have a TypeScript/Node.js bias
>
> You'll want to customize or remove these to match your own workflow.

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

# Copy Claude-specific content (commands and workflow rules)
cp -r src/user/.claude/commands ~/.claude/
cp -r src/user/.claude/rules ~/.claude/

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
4. **Tool-specific extensions** — Remove rules for plugins you don't use:
   - **Claude:** workflow rules live in `src/user/.claude/rules/` — `delegation.md`, `completion-gate.md`, `delivery.md`, `git-commits.md`, `codex-routing.md`, `subagents.md`. `delegation` and `completion-gate` reference superpowers skills; `delivery` wires worktree isolation, PR creation, and Copilot review monitoring
   - **Beads plugin** (`src/plugins/beads/`) — adds `beads.md` to `rules/` at install time; assumes [beads](https://github.com/steveyegge/beads)
   - **Codex/Gemini** — see `CODEX-EXTENSIONS.md` or `GEMINI-EXTENSIONS.md`
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
