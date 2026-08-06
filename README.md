# agents-config

Versioned collection of skills, rules, commands, and templates for AI coding assistants. Supports **Claude Code**, **OpenAI Codex CLI**, **Google Gemini CLI**, and **OpenCode**. Shared content is installed to all detected tools; tool-specific content goes only where it belongs.

> **New here and want to _use_ this?** Start with the **[User Guide](./docs/guide/index.md)** — install, configure a project, and run the opinionated agentic SDLC. This README is the project overview and installer reference.

## Vision

**The goal**: make AI software development reliably autonomous, so humans spend most of their time *upstream* — on brainstorming, design, and judgment — and very little time downstream chasing the AI's mistakes.

If the harness works as intended, an idealized "day in the life" looks like:

- **~85% of human time** in brainstorming and design — articulating intent, pinning requirements, choosing trade-offs
- **~5% of human time** triaging escalations from autonomous runs — when an agent legitimately cannot decide on its own
- **~10% of human time** doing validation testing that machines genuinely cannot do (UX feel, requirements alignment, edge-case judgment)
- **Cycle time from idea to shippable software is noticeably shorter** than naked-LLM use, because implementation and machine-verifiable QA happen in the background, including overnight

The five load-bearing convictions behind this:

1. **Methodology is the moat, not the model.** Skills define HOW (design, spec-writing, review, delegation); agents define WHO; the underlying model is interchangeable.
2. **AI must be good at saying "no, not ready."** Under-specified work should bounce back to the human BEFORE implementation, with structured feedback on what is missing — not after a wasted autonomous run.
3. **Adversarial cross-model review is a first-class substitute for human review.** Different models have different blind spots; multi-model dialectic catches what a single model misses.
4. **Evidence before assertion, always.** Mechanical gates (tests, build, lint, review) sit between "I think this works" and "this is done."
5. **Persistent context survives compaction.** Tracked work items and handoff documents let work span sessions, agents, and overnight cranking without losing thread.

### Current state — mid-rebuild

**The harness is being rebuilt, and a large part of what this repo used to ship no longer exists.** The completion gate, the merge guard, the PR-feedback skills, the planning and test-first skills, and every role-based agent definition were retired; their replacements are specified but mostly not built. What ships today is a much smaller set: the always-on instruction core (laws, decision matrix, hard lines), the design and spec-writing path (`grilling`, `to-spec`, `ac-attack`), the review contracts (`review-panel`, `review-verdict`), the delegation skills, and git cleanup.

The plan of record is [`docs/specs/2026-07-21-harness-rework-way-forward.md`](./docs/specs/2026-07-21-harness-rework-way-forward.md) — decisions, acceptance criteria, and the ordered slice list. Read it before building on anything here. Live status lives in the tracker, not in this file.

Where this README and the source tree disagree, believe the source tree.

## Prerequisites

- **An AI coding assistant** — Claude Code, OpenAI Codex CLI, Google Gemini CLI, or OpenCode. The installer detects which you have.
- **`uv`** — the installer is a uv-managed Python package (auto-installs Python ≥3.11 on first run). `uv` ≥ 0.10.4 is required for the stage that deploys this repo's CLIs onto PATH.

Nothing else is required. Two former prerequisites are now optional:

- **[steveyegge/beads](https://github.com/steveyegge/beads)** — the `bd` tracker. The `work` CLI this repo installs is a facade over `bd` and needs it to function, but nothing in the installed instruction surface requires either.
- **[obra/superpowers](https://github.com/obra/superpowers)** — no longer a dependency. The rules and skills that referenced its process skills were retired.

The `codex` plugin under `src/plugins/` is auto-detected when `~/.codex/` exists — a `codex` binary on PATH alone will not trigger it — and its skill assumes the [Codex CLI](https://github.com/openai/codex) is available.

## What's Inside

```
scripts/
├── install.sh                      # Thin exec stub → packages/installer (uv-managed Python)
└── install.py                      # Python entry point (uv run python -m installer)
packages/                           # Real Python packages (standalone uv projects, not installed config)
│                                   #   See the Makefile for which are CI-gated, and
│                                   #   core/clis.py for which deploy onto PATH
├── installer/                      # The installer engine
├── workcli/                        # The `work` issue-tracker facade CLI
├── prgroom/                        # PR-grooming CLI (carved, not finished)
├── grind/                          # Event-sourced runtime: event schema + FSM fold
├── executor/                       # Verb→event→tracker pairing layer (no dispatch loop yet)
├── gitclean/                       # Provably-merged branch and worktree sweeper
└── …                               # Plus earlier-stage packages
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
│   │   ├── rules/                  # Shared always-on rules (empty today)
│   │   ├── skills/                 # Methodology guides with examples
│   │   └── USER-CORE.md.template   # Zero-based laws, decision matrix, hard lines, conventions
│   ├── .claude/                    # Claude-specific (→ ~/.claude/)
│   │   ├── commands/               # Slash commands
│   │   ├── skills/                 # Claude-only skills
│   │   ├── rules/                  # Claude-specific rules
│   │   ├── hooks/                  # PostToolUse / SessionStart hooks
│   │   ├── AGENTS.md.template      # Claude instruction file
│   │   ├── CLAUDE.md.template      # Points to AGENTS.md
│   │   └── settings.json.template  # Permissions, hooks & experimental features
│   ├── .codex/                     # Codex-specific (→ ~/.codex/)
│   ├── .gemini/                    # Gemini-specific (→ ~/.gemini/)
│   └── .opencode/                  # OpenCode-specific (→ ~/.config/opencode/), + opencode.jsonc.template
└── plugins/                        # Optional plugin content (auto-discovered, installed when detected)
    └── codex/                      # codex plugin: model-routing skill for a Codex run (Claude-only)
```

> Not everything under `src/` is a wrapper around a single tool: shared content
> in `.agents/` installs to **all** detected tools; `.claude/`, `.codex/`,
> `.gemini/`, and `.opencode/` add tool-specific pieces. The `packages/` are real
> code, not installed configuration.

### What actually deploys

Being in `src/` is necessary but not sufficient. Every rule, skill, command and
agent must carry a complete **admission record** in its front matter — what it
prevents or provides, what it costs, and what observation would remove it.
Anything without one is dropped at install and pruned on the next run, wherever
it sits, plugin trees included. `src/user/.agents/rules/` is empty today for
exactly that reason.

Rather than duplicate a list that goes stale, read the directories — they are
the authoritative inventory:

| What | Where | Installs to |
|------|-------|-------------|
| Shared skills | [`src/user/.agents/skills/`](./src/user/.agents/skills/) | every detected tool |
| Shared rules | [`src/user/.agents/rules/`](./src/user/.agents/rules/) | every detected tool |
| Claude-only skills | [`src/user/.claude/skills/`](./src/user/.claude/skills/) | `~/.claude/skills/` |
| Claude-only rules | [`src/user/.claude/rules/`](./src/user/.claude/rules/) | `~/.claude/rules/` |
| Slash commands | [`src/user/.claude/commands/`](./src/user/.claude/commands/) | `~/.claude/commands/` |
| Plugin content | [`src/plugins/`](./src/plugins/) | matching tools, when detected |

Each `rules/` directory carries its own `AGENTS.md` stating what currently lives
there. For a walkthrough of what the installed set does and where the gaps are,
see [The SDLC Workflow](./docs/guide/sdlc-workflow.md).

### Agents

**None ship.** The role-based agent definitions (`quality-reviewer`, `tech-lead`
and the rest) were retired in the rebuild and have no replacement yet. The
installer still supports an `agents/` namespace, so this section will come back;
today `~/.claude/agents/` gets nothing from this repo.

### Commands

Slash commands that can be invoked directly. Claude Code only — commands are a
tool-scoped namespace with no shared variant:

- `/clean-up-git [filter]` - Adjudicate which git worktrees and branches to
  delete: one dated table with each worktree paired to its branch and every
  deletion's cost stated, then a stop for your call before anything is touched

See [`src/user/.claude/commands/`](./src/user/.claude/commands/) for the
authoritative set.

### Templates

**Shared** (in `src/user/.agents/`):
- `USER-CORE.md.template` — the zero-based always-on core: laws, decision matrix, hard lines, conventions. This is the substance of every tool's instruction file.

**Per-tool:**
- `src/user/.claude/AGENTS.md.template` — Claude instruction file
- `src/user/.claude/CLAUDE.md.template` — minimal file pointing at `AGENTS.md`
- `src/user/.claude/settings.json.template` — permissions, hooks, experimental features
- `src/user/.codex/AGENTS.md.template`, `src/user/.gemini/GEMINI.md.template`, `src/user/.opencode/AGENTS.md.template` — the equivalent instruction files
- `src/user/.opencode/opencode.jsonc.template` — OpenCode settings

There are no persona templates. The `USER-PERSONA.md` / `AGENT-PERSONA.md` pair
that earlier versions shipped was retired: the always-on surface is now
zero-based and carries no identity content.

> **Note:** some of what ships still reflects the author's setup — the
> `settings.json` experimental flags and taste keys most obviously, and some
> constraints carry a Python/TypeScript bias. Customize or remove to match your
> own workflow.

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
- Enforces the **admission bar**: drops (and prunes) any rule, skill, command or agent whose front matter lacks a complete `admission:` record, and strips that repo-side bookkeeping from the bytes it deploys
- Deploys this repo's CLIs onto PATH via `uv tool install` (receipt-tracked, pruned on retirement); `CLI_PACKAGES` in `packages/installer/src/installer/core/clis.py` is the authoritative list
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
| `--plugins=PLUGINS` | Comma-separated plugin list, discovered under `src/plugins/`; default auto-detect; pass `--plugins=` to disable all |
| `--project=PATH` | Install project-scoped content into PATH instead of user space |
| `--profiles=CSV` | Profile names to install (requires `--project`) |
| `--prune` | After install, remove orphans (items the install receipt no longer owns) under the managed namespaces, with backup |
| `--prune-only` | Skip install; only scan + prune orphans (mutually exclusive with `--prune`) |
| `--dump-stage=DIR` | Debug: materialize the in-memory staging plan to a directory tree instead of installing |
| `--help`, `-h` | Show help |

`--prune`, `--prune-only` and `--dump-stage` are mutually exclusive.

#### Pruning orphans

`--prune` and `--prune-only` identify and (optionally) remove items the installer
previously owned but no longer ships — useful for keeping your install in sync
after files are renamed or deleted upstream.

- **Receipt-based, not glob-based:** each install writes an **install receipt** recording exactly what it owns (a roots allowlist plus a per-entry digest). Pruning diffs the current staging plan against that receipt, so it removes precisely the items the repo dropped — not whatever happens to sit in a namespace directory. Files you added yourself outside the owned set are not touched.
- **Scope:** the managed namespaces (`commands` / `skills` / `agents` / `rules` under each tool's config dir, plus any bespoke routes an active plugin declares outside the tool trees). Top-level `*.md`, `settings.json`, and `hooks/` are never pruned.
- **Backups:** orphans are moved to a `<namespace>-backup/<basename>.backup-<timestamp>` sibling before deletion; those `*-backup/` siblings are excluded from future scans.
- **Modes:**
  - `--dry-run` lists orphans and exits without changes.
  - `--yes` backs up + deletes all orphans without prompting.
  - Interactive (default): displays orphans, then prompts `[a]ll / [o]ne-by-one / [c]ancel`. Cancel and EOF leave everything in place.
  - Non-interactive without `--yes` or `--dry-run`: `--prune` warns and skips the prune phase (install still runs); `--prune-only` hard-fails (exit non-zero).

### Manual

The installer does more than copy — it enforces the admission bar, strips
repo-side bookkeeping from the deployed bytes, union-merges settings, and writes
a receipt so pruning is precise. Copying by hand skips all of that, so prefer
`./scripts/install.sh`. If you want a subset anyway:

```bash
# Shared skills (installed to every tool by the installer)
cp -r src/user/.agents/skills ~/.claude/

# Claude-specific content
cp -r src/user/.claude/skills ~/.claude/
cp -r src/user/.claude/commands ~/.claude/
cp -r src/user/.claude/rules ~/.claude/
cp -r src/user/.claude/hooks ~/.claude/

# Instruction files and settings
cp src/user/.agents/USER-CORE.md.template ~/.claude/AGENTS.md
cp src/user/.claude/CLAUDE.md.template ~/.claude/CLAUDE.md
cp src/user/.claude/settings.json.template ~/.claude/settings.json
```

### Project-level (applies to specific project)

Use `./scripts/install.sh --project=/path/to/your/project`, which stages
project-scoped content properly. The blunt equivalent:

```bash
cd /path/to/your/project
cp -r /path/to/agents-config/src/user/.agents/skills .claude/
cp -r /path/to/agents-config/src/user/.claude/commands .claude/
```

### Customizing what you installed

- **`settings.json`** (Claude only) — the shipped `allow` list is empty by design; add your own safe-command entries to cut permission prompts. The `deny` list, the hooks, and the experimental env flags are all worth reading before you keep them.
- **Rules** — remove any rule you don't want from your tool's `rules/` directory. Read the `AGENTS.md` in each source `rules/` directory for what currently lives there.
- **Plugins** — `--plugins=` (empty) installs none; `--plugins=<names>` picks an explicit set.

The instruction files (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`) are thin wrappers
around the shared core and generally need no changes.

## Scope: User vs Project

Claude Code looks for configuration in multiple locations with the following precedence:

| Location | Scope | Use Case |
|----------|-------|----------|
| `~/.claude/` | User (global) | Personal preferences, skills you always want available |
| `.claude/` in project | Project | Project-specific skills, commands, and settings |

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

The deeper capability roadmap — the harness rebuild itself — is the ordered
slice list in
[`docs/specs/2026-07-21-harness-rework-way-forward.md`](./docs/specs/2026-07-21-harness-rework-way-forward.md).
Live status is in the tracker (`work show agents-config-9k9`), not in any
document here; the charter deliberately tracks no progress.

## Contributing

This is currently a personal configuration repository. If you find it useful and want to contribute agents or skills, open an issue to discuss.

## License

MIT - Use however you like.
