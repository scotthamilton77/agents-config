# agents-config

Versioned collection of agents, skills, commands, and templates for AI coding assistants. Supports **Claude Code**, **OpenAI Codex CLI**, **Google Gemini CLI**, and **OpenCode**. Shared content is installed to all detected tools; tool-specific content goes only where it belongs.

> **New here and want to _use_ this?** Start with the **[User Guide](./docs/guide/index.md)** — install, configure a project, and run the opinionated agentic SDLC. This README is the project overview and installer reference.

## Vision

**The goal**: make AI software development reliably autonomous, so humans spend most of their time *upstream* — on brainstorming, design, and judgment — and very little time downstream chasing the AI's mistakes.

If the harness works as intended, an idealized "day in the life" looks like:

- **~85% of human time** in brainstorming and design — articulating intent, pinning requirements, choosing trade-offs
- **~5% of human time** triaging escalations from autonomous runs — when an agent legitimately cannot decide on its own
- **~10% of human time** doing validation testing that machines genuinely cannot do (UX feel, requirements alignment, edge-case judgment)
- **Cycle time from idea to shippable software is noticeably shorter** than naked-LLM use, because implementation and machine-verifiable QA happen in the background, including overnight

The five load-bearing convictions behind this:

1. **Methodology is the moat, not the model.** Skills define HOW (TDD, brainstorming, verification, adversarial review); agents define WHO; the underlying model is interchangeable.
2. **AI must be good at saying "no, not ready."** Under-specified work should bounce back to the human BEFORE implementation, with structured feedback on what is missing — not after a wasted autonomous run.
3. **Adversarial cross-model review is a first-class substitute for human review.** Different models have different blind spots; multi-model dialectic catches what a single model misses (RALF, foreign-CLI, codex adversarial review).
4. **Evidence before assertion, always.** Mechanical gates (tests, build, lint, review) sit between "I think this works" and "this is done."
5. **Persistent context survives compaction.** Beads, memories, formulas, and audit logs let work span sessions, agents, and overnight cranking without losing thread.

### Current state

The core architecture is in place, and several keystone enablers have shipped since the first cut: a canonical decision matrix that resolves the decide-vs-escalate direction, a three-tier completion gate (SKIP/SERIAL/HEAVY) that scales verification to the diff, a two-axis review/merge policy (`never` / `explicit` / `rule-based`) enforced by `merge-guard`, and the `prgroom` CLI + `monitor-pr` skill that make PR grooming deterministic. Notable remaining gaps:

- The "no, not ready" brainstorm-readiness gate is implicit, not enforced (milestone M2)
- The 85/5/10 ratio is not yet instrumented — aspirational, not measured
- No spec post-mortem feedback loop yet — failures don't automatically improve future brainstorming
- Rule-based auto-merge exists but is opt-in per repo; most repos still default to `explicit` (a human "ship it") — though on a protected branch it can satisfy the required review via an App-attested approver (`[merge-policy.approver]`)
- The PDLC Orchestrator (the FSM that would run overnight autonomy) is an early tracer bullet — CLI, durable state, and the strike/recovery machine are designed, not built (milestone M4)

Treat the vision as direction and the rules-as-written as the current contract. Contributions are welcome.

## Prerequisites

This configuration relies on two Claude Code plugins being installed:

- **[obra/superpowers](https://github.com/obra/superpowers)** - Provides the skill/agent framework referenced throughout: brainstorming, TDD, verification-before-completion, dispatching-parallel-agents, finishing-a-development-branch, and more
- **[steveyegge/beads](https://github.com/steveyegge/beads)** - Git-backed issue tracker providing the `bd` command used for task tracking in the AGENTS.md template

Without these plugins, several shared workflow rules (`delegation`, `completion-gate` under `src/user/.agents/rules/`, and `beads` under `src/plugins/beads/`) will reference skills and commands that don't exist.

**Optional integrations** (each degrades gracefully if absent):

- **`prgroom` CLI** — the `monitor-pr` skill drives it for deterministic PR grooming. It is a standalone package (`packages/prgroom/`) and is **not** installed by the installer; `uv tool install` it from that directory if you want the `monitor-pr` path. The skill-based `wait-for-pr-comments` path works without it.
- **beads / graphify / codex plugins** (`src/plugins/`) — auto-detected and installed only when their footprint is present (`bd`/`~/.beads/`, `~/.graphify/`, `~/.codex/`). The `codex` plugin's routing rule additionally assumes the [Codex CLI plugin](https://github.com/openai/codex).

## What's Inside

```
scripts/
├── install.sh                      # Thin exec stub → packages/installer (uv-managed Python)
└── install.py                      # Python entry point (uv run python -m installer)
packages/                           # Real Python packages (standalone uv projects, not installed config)
├── installer/                      # The installer engine; CI-gated (make ci-installer)
├── prgroom/                        # Deterministic PR-grooming CLI; CI-gated (make ci-prgroom)
├── pdlc/                           # PDLC Orchestrator FSM engine (early)
└── holding-place/                  # Idea pipeline + Promote contract to PDLC (early)
docs/
├── guide/                          # User guide — how to configure a project & run the SDLC
├── architecture/                   # Evergreen HLD artifacts (C4, sequence, state machines) per subsystem
├── primers/                        # Prose explainers for the discipline-layer primitives
├── specs/                          # Dated, point-in-time design proposals
├── plans/                          # Dated implementation plans
└── adr/                            # Architecture decision records
src/
├── user/
│   ├── .agents/                    # Shared content (copied into all detected tools)
│   │   ├── agents/                 # Role-based agent definitions
│   │   ├── rules/                  # Shared workflow rules (delegation, completion-gate, subagents, worktrees, …)
│   │   ├── skills/                 # Methodology guides with examples
│   │   ├── AGENTS.md.template             # Zero-based shared laws, decision matrix, hard lines
│   │   ├── AGENT-PERSONA.md.template     # Agent persona/personality
│   │   └── USER-PERSONA.md.template      # User persona
│   ├── .claude/                    # Claude-specific (→ ~/.claude/)
│   │   ├── commands/               # Slash commands
│   │   ├── skills/                 # Claude-only skills (e.g. orchestrating-subagents)
│   │   ├── rules/                  # Claude-specific rules (claude-sandbox, headless-claude, orchestrating-subagents, worktree-safety)
│   │   ├── AGENTS.md.template      # Claude instruction file
│   │   ├── CLAUDE.md.template      # Points to AGENTS.md
│   │   ├── CLAUDE-EXTENSIONS.md.template  # Stub header (content moved to rules/)
│   │   └── settings.json.template  # Permissions, hooks & experimental features
│   ├── .codex/                     # Codex-specific (→ ~/.codex/)
│   ├── .gemini/                    # Gemini-specific (→ ~/.gemini/)
│   └── .opencode/                  # OpenCode-specific (→ ~/.config/opencode/)
└── plugins/                        # Optional plugin content (auto-discovered, installed when detected)
    ├── beads/                      # beads plugin: bd CLI gotcha + discovered-work rules
    ├── graphify/                   # graphify plugin: graphify discipline rule
    └── codex/                      # codex plugin: Codex routing rule (Claude-only)
```

> Not everything under `src/` is a wrapper around a single tool: shared content
> in `.agents/` installs to **all** detected tools; `.claude/`, `.codex/`,
> `.gemini/`, and `.opencode/` add tool-specific pieces. The `packages/` are real
> code, not installed configuration.

### Agents

Role-specific configurations that define expertise areas, behavioral patterns, and domain knowledge. Each agent file has YAML frontmatter (name, description, model, color) followed by role definition, domain-specific standards, and boundaries. See [`src/user/.agents/agents/`](./src/user/.agents/agents/) for the full set.

Shipping agents:

- `quality-reviewer` — proactive code quality/security/maintainability review plus plan-vs-implementation drift detection
- `tech-lead` — orchestrates complex multi-step work across specialized agents and skills (no Write/Edit tools)
- `pr-comment-fixer-team` — fixes a single PR review comment; invoked per-comment by the PR-feedback flow

### Skills

Deep methodology guides for specific tasks. Unlike agents (which define *who*), skills define *how* to approach particular problems. The set below ships from this repo; process skills referenced by the workflow rules (e.g. `brainstorming`, `test-driven-development`) come from the [superpowers](https://github.com/obra/superpowers) plugin (see Prerequisites).

**Process / gate skills** — the backbone of the opinionated workflow:

| Skill | Purpose |
|-------|---------|
| `bugfix` | Parallel debugging investigation with systematic root-cause analysis |
| `writing-plans` | Turn a spec/requirements into a multi-step plan before touching code |
| `writing-unit-tests` | Test behavior, not implementation; when to refuse testing untestable code |
| `test-review` | Code review of unit/integration tests for quality and design issues |
| `gate-triage` | Deterministic completion-gate router — computes the SKIP/SERIAL/HEAVY tier as JSON |
| `simplify` | Review changed code for reuse/quality/efficiency and fix what it finds |
| `verify-checklist` | Structured completion auditing with evidence requirements |
| `using-git-worktrees` | Ensure an isolated workspace exists before feature work |
| `finishing-a-development-branch` | Decide how to integrate completed work (merge / PR / cleanup) |
| `merge-guard` | Pre-merge enforcement of the repo's two-axis review/merge policy |
| `self-improving-agent` | Persist lessons from user corrections as actionable rules |
| `retrospect` | Session retrospective — what slowed things down, what to improve |
| `orchestrating-subagents` | Coordination contract for dispatching and nesting subagents (Claude-only) |

**PR-feedback skills** — the `monitor-pr` skill drives the `prgroom` CLI (see `packages/prgroom/`); the older skill-based path is still shipped:

| Skill | Purpose |
|-------|---------|
| `monitor-pr` | Supervise a PR through the `prgroom` grooming loop |
| `wait-for-pr-comments` | Copilot-aware PR feedback handler: polls, classifies (FIX/SKIP/ESCALATE), fixes via per-comment subagents, pushes, then chains `reply-and-resolve-pr-threads` |
| `reply-and-resolve-pr-threads` | Reply to every PR review thread; resolve only the FIXED ones via GraphQL |

**Domain / authoring skills:**

| Skill | Purpose |
|-------|---------|
| `ralf-review` | Bounded adversarial fresh-eyes review cycles for specs, designs, or code (explicit invocation) |
| `ralf-implement` | Iterative implementation refinement with adversarial fresh-eyes passes (explicit invocation) |
| `grill-with-docs` | Stress-test a plan against the project's domain model; update CONTEXT.md/ADRs inline |
| `improve-codebase-architecture` | Find deepening/refactoring opportunities informed by CONTEXT.md and ADRs |
| `prototype` | Build a throwaway prototype (terminal app or UI variations) to flesh out a design |
| `optimize-agents-md` | Optimize CLAUDE.md/AGENTS.md files (size, redundancy, merging) |
| `optimize-my-agent` | Audit and improve an agent persona file |
| `optimize-my-skill` | Audit and improve a SKILL.md |
| `whats-next` | Surface the right beads work list for the session |
| `where-does-this-fit` | Explain how a work item fits the broader project architecture |
| `caveman` | Ultra-compressed communication mode (~75% token cut) |

See [`src/user/.agents/skills/`](./src/user/.agents/skills/) for the authoritative set.

### Commands

Slash commands that can be invoked directly:

- `/optimize-my-agent <path>` - Analyze and improve an agent definition file
- `/optimize-my-skill <path>` - Analyze and improve a skill definition
- `/refresh-agents-md` - Regenerate AGENTS.md from current repo state

### Templates

**Shared** (in `src/user/.agents/`):
- `AGENTS.md.template` - Zero-based shared laws, decision matrix, hard lines, and conventions (D17). Hand-deployed to the standard homes (S0); not yet wired into automated per-tool assembly (`agents-config-9k9.10`)
- `AGENT-PERSONA.md.template` - Agent personality and behavioral traits (referenced via `@AGENT-PERSONA.md`)
- `USER-PERSONA.md.template` - User description and interaction preferences (referenced via `@USER-PERSONA.md`)

**Claude-specific** (in `src/user/.claude/`):
- `AGENTS.md.template` - Claude instruction file referencing shared persona/session-primer content + Claude extensions
- `CLAUDE.md.template` - Minimal file that points to AGENTS.md
- `CLAUDE-EXTENSIONS.md.template` - Stub header (content moved to `rules/`)
- `settings.json.template` - Pre-configured permission allowlists, hooks, and experimental features

> **Note:** The templates contain content specific to the author's setup:
> - The persona templates reflect personal interaction preferences
> - The `beads` plugin (under `src/plugins/beads/`) assumes use of [steveyegge/beads](https://github.com/steveyegge/beads) as a task tracker
> - The `delegation` and `completion-gate` rules (in `src/user/.agents/rules/`) assume [obra/superpowers](https://github.com/obra/superpowers) skills are available
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

# Install AND remove orphaned items not in the source (with backup)
./scripts/install.sh --prune

# Skip install; only scan + prune orphans
./scripts/install.sh --prune-only --dry-run    # preview
./scripts/install.sh --prune-only --yes        # execute
```

The installer (`scripts/install.sh`) is a thin exec stub backed by a uv-managed Python package (`packages/installer`). It:
- Auto-detects installed tools (Claude Code, Codex CLI, Gemini CLI, OpenCode) or use `--tools=` to override
- Copies shared content (`src/user/.agents/`) into all detected tools
- Copies tool-specific content (e.g., `src/user/.claude/`) into the corresponding tool's config directory
- Copies `*.md.template` files (stripping `.template` suffix), with diff preview and confirmation for existing files
- Syncs `agents/`, `skills/`, `commands/`, and `rules/` directories using hash comparison per item, and a recursive digest to detect drift inside owned directories
- Union-merges `settings.json.template` into existing `settings.json` via a pluggable per-key merge registry (preserves your values, adds new keys/entries)
- Records an **install receipt** of what it owns, so pruning is a precise diff against the last install rather than a glob guess
- Honors a shared `.installignore` manifest that excludes source-only files (test fixtures, rationale docs) from install
- Creates timestamped backups before overwriting anything
- Warns about items that aren't tracked in the project (or removes them with `--prune`)

Requires `uv` (auto-installs Python ≥3.11 on first run). Use `--dry-run` to preview changes without writing.

#### Flags

| Flag | Purpose |
|------|---------|
| `--dry-run` | Show what would change without writing |
| `--yes`, `-y` | Auto-accept all prompts (suppresses diffs in quiet mode) |
| `--verbose`, `-v` | Per-file progress (phases, up-to-date, installed, diffs) |
| `--tools=TOOLS` | Comma-separated tool list (`claude`, `codex`, `gemini`, `opencode`); default auto-detect |
| `--plugins=PLUGINS` | Comma-separated plugin list (`beads`, `graphify`, `codex`); default auto-detect; pass `--plugins=` to disable all |
| `--prune` | After install, remove orphans (items the install receipt no longer owns) under the managed namespaces, with backup |
| `--prune-only` | Skip install; only scan + prune orphans (mutually exclusive with `--prune`) |
| `--dump-stage=DIR` | Debug: materialize the in-memory staging plan to a directory tree instead of installing |
| `--help`, `-h` | Show help |

#### Pruning orphans

`--prune` and `--prune-only` identify and (optionally) remove items the installer
previously owned but no longer ships — useful for keeping your install in sync
after files are renamed or deleted upstream.

- **Receipt-based, not glob-based:** each install writes an **install receipt** recording exactly what it owns (a roots allowlist plus a per-entry digest). Pruning diffs the current staging plan against that receipt, so it removes precisely the items the repo dropped — not whatever happens to sit in a namespace directory. Files you added yourself outside the owned set are not touched.
- **Scope:** the managed namespaces (`commands` / `skills` / `agents` / `rules` under each tool's config dir, plus beads' `~/.beads/` routes). Top-level `*.md`, `settings.json`, and `hooks/` are never pruned.
- **Backups:** orphans are moved to a `<namespace>-backup/<basename>.backup-<timestamp>` sibling before deletion; those `*-backup/` siblings are excluded from future scans.
- **Modes:**
  - `--dry-run` lists orphans and exits without changes.
  - `--yes` backs up + deletes all orphans without prompting.
  - Interactive (default): displays orphans, then prompts `[a]ll / [o]ne-by-one / [c]ancel`. Cancel and EOF leave everything in place.
  - Non-interactive without `--yes` or `--dry-run`: `--prune` warns and skips the prune phase (install still runs); `--prune-only` hard-fails (exit non-zero).

### Manual

```bash
# Copy shared content (agents, skills)
cp -r src/user/.agents/agents ~/.claude/
cp -r src/user/.agents/skills ~/.claude/

# Copy Claude-specific content (commands and workflow rules)
cp -r src/user/.claude/commands ~/.claude/
cp -r src/user/.claude/rules ~/.claude/

# Copy and customize shared templates
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
3. **Tool-specific extensions** — Remove rules for plugins you don't use:
   - **Claude:** shared workflow rules live in `src/user/.agents/rules/` — `delegation.md`, `completion-gate.md`, `subagents.md`, `worktrees.md`, `memory-routing.md`, `user-prompts.md`, `bash-scripting.md`; Claude-specific rules in `src/user/.claude/rules/` — `claude-sandbox.md`, `headless-claude.md`, `orchestrating-subagents.md`, `worktree-safety.md`. `delegation` and `completion-gate` reference superpowers skills; delivery (worktree isolation → PR creation → review monitoring) is now handled by the `using-git-worktrees`, `finishing-a-development-branch`, and `monitor-pr`/`wait-for-pr-comments` skills rather than a standalone rule
   - **Beads plugin** (`src/plugins/beads/`) — adds `beads.md` to `rules/` at install time; assumes [beads](https://github.com/steveyegge/beads)
   - **Codex/Gemini** — see `CODEX-EXTENSIONS.md` or `GEMINI-EXTENSIONS.md`
4. **`settings.json`** (Claude only) — Adjust permission allowlists, hooks, and deny rules to match your needs

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

Installer / distribution:

- [x] **Gemini support** — Equivalent configurations for Google's Gemini
- [x] **Codex support** — Equivalent configurations for OpenAI's Codex
- [x] **OpenCode support** — Equivalent configurations for OpenCode
- [ ] **Selectable extension bundles** — Task tracker, language preferences, etc. applied at install time
- [ ] **Update mechanism** — Pull latest versions without clobbering customizations
- [ ] **Selective install** — Choose which agents/skills to include
- [ ] **Agent marketplace** — Community-contributed agents and skills

The deeper capability roadmap (brainstorm-readiness gate, worker fleet, overnight
autonomy) is tracked as milestone beads — `bd list --type milestone` — and
summarized in the repo's `AGENTS.md`.

## Contributing

This is currently a personal configuration repository. If you find it useful and want to contribute agents or skills, open an issue to discuss.

## License

MIT - Use however you like.
