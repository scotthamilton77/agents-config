# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Project Purpose

This is a versioned collection of agents, skills, commands, and templates for AI coding assistants. Supports **Claude Code**, **OpenAI Codex CLI**, **Google Gemini CLI**, and **OpenCode**. Shared content is installed to all detected tools; tool-specific content goes only where it belongs.

## Vision & Mission

**Vision** — Make AI software development reliably autonomous. Concentrate human time *upstream* (brainstorming, design, judgment) and at thin verification gates (validation testing, exception handling); have agents execute implementation and machine-verifiable QA in the background, including overnight.

**Target operating ratio (aspirational, not yet measured)** — roughly **85% / 5% / 10%** of human time on brainstorming / troubleshooting escalations / validation testing, with a noticeably shorter idea-to-shippable cycle time than naked-LLM use.

**Mission** — Ship a portable discipline layer (agents, skills, commands, formulas, plugins) that makes that operating ratio achievable on any major AI coding assistant. The mechanism rests on five load-bearing commitments:

1. **Frontload human creativity & judgment** via rigorous brainstorming and a spec-readiness gate
2. **Make AI good at saying "no, not ready"** — bounce under-specified work back BEFORE implementation, with structured feedback on what is missing
3. **Substitute adversarial cross-model review** for human review wherever quality permits (RALF, foreign-CLI configs, codex adversarial review)
4. **Guardrail every completion claim with mechanical evidence** (completion gate, verify-checklist)
5. **Persist context** (beads, memories, formulas) so work survives compaction, agent handoff, and overnight runs

### Current state — work in progress

The architecture is in place; several keystone enablers are tracked but **not yet shipped**. Treat the vision as direction; treat the rules-as-written as the current contract.

Search current work with: `bd list --label vision-85-5-10`. Major gaps as of 2026-05:

- **Brainstorm-readiness gate** — the "no, not ready" mechanism is implicit, not enforced
- **Persona vs orchestration** guidance on decide-vs-escalate is not yet reconciled
- **85/5/10 instrumentation** — aspirational, not measured
- **Spec post-mortem** feedback loop — not built; failures do not automatically improve future brainstorming
- **Risk-tiered auto-merge** for low-risk PR classes — not defined; every PR waits on a human "ship it"
- **Wall-clock pipelining** across external waits (CI, Copilot, GitHub) — future work

### Implications for agents working in *this* repo

- **File beads for harness friction you discover** — refining this discipline layer IS the work; capture is not a tangent
- **Surface rule conflicts**, do not paper over them; if persona and orchestration disagree, say so
- **When proposing new skills, agents, or rules, ask**: does this advance the 85/5/10 ratio, or accidentally regress it?
- **Distinguish the destination from the contract** in your reasoning: don't behave as if a vision-tagged enabler exists when it doesn't, but do let the vision break ties when the rules are silent

## Prerequisites (Plugins)

This configuration assumes the following Claude Code plugins are installed:

- **[obra/superpowers](https://github.com/obra/superpowers)** - Provides skills referenced throughout the templates: brainstorming, TDD, verification-before-completion, dispatching-parallel-agents, writing-plans, and others
- **[steveyegge/beads](https://github.com/steveyegge/beads)** - Git-backed issue tracker providing the `bd` command used in the `<beads>` section of the AGENTS.md template

## Repository Structure

- `scripts/` - Installation and maintenance scripts
  - `install.sh` - Multi-tool installer with auto-detection, `--dry-run`, `--tools=`/`--plugins=` overrides, and `--prune`/`--prune-only` for removing orphaned items not in the source
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
  - `rules/` - Claude-specific workflow rules (delegation, completion-gate, delivery, git-commits, codex-routing, subagents)
  - `AGENTS.md.template` - Claude instruction file (refs shared + Claude extensions)
  - `CLAUDE.md.template` - Points to AGENTS.md
  - `CLAUDE-EXTENSIONS.md.template` - Stub header (content moved to `rules/`)
  - `settings.json.template` - Permission presets, hooks, and experimental features
- `src/user/.codex/` - **Codex-specific** content (copies to `~/.codex/`)
  - `AGENTS.md.template` - Codex instruction file (refs shared + Codex extensions)
  - `CODEX-EXTENSIONS.md.template` - Codex-specific sections (placeholder)
- `src/user/.gemini/` - **Gemini-specific** content (copies to `~/.gemini/`)
  - `GEMINI.md.template` - Gemini instruction file (refs shared + Gemini extensions)
  - `GEMINI-EXTENSIONS.md.template` - Gemini-specific sections (placeholder)
- `src/user/.opencode/` - **OpenCode-specific** content (flattens to `~/.config/opencode/`)
  - `AGENTS.md.template` - Flat instruction skeleton with dynamic-include markers
  - `OPENCODE-EXTENSIONS.md.template` - OpenCode-specific notes and conventions
  - `opencode.jsonc.template` - Settings (model, permissions, skills paths)
- `src/plugins/` - **Optional plugin content** (installed only when detected)
  - `beads/` - beads plugin: skills, Claude rules, formulas
  - See `src/plugins/AGENTS.md` for plugin authoring conventions

## File Formats

### Agent files (`agents/*.md`)

```yaml
---
name: agent-name
description: One-line description
model: sonnet | opus | haiku | inherit          # optional; common subset — see AGENTS_PRIMER.md for full list (e.g. opus[1m], sonnet[1m])
color: purple | indigo | blue | green | yellow | orange | red | cyan | teal | pink
tools: Read, Grep, Glob, Bash                   # optional — comma-separated allow-list
disallowedTools: Write, Edit                    # optional — explicit deny-list
skills: [skill-name, plugin:skill-name]         # optional — preloaded skills
effort: low | medium | high | xhigh             # optional — reasoning budget
memory: <path-or-key>                           # optional — persistent memory namespace
---
```

See `docs/primers/AGENTS_PRIMER.md` for the full schema and field semantics.

Followed by role definition, standards, and boundaries.

### Skill files (`skills/*/SKILL.md`)

```yaml
---
name: skill-name
description: When to use this skill
# optional fields: model, effort, allowed-tools — see docs/primers/SKILLS_PRIMER.md
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
- **No file-path citations in specs or prose** — `INSTRUCTIONS.md.template` and all shared templates are flattened into per-tool assembled files at install time via `DYNAMIC-INCLUDE`. File-path citations (`INSTRUCTIONS.md > <section>`) are dead-ends after assembly. Always reference shared content by concept or block name (e.g., "the canonical decision matrix", "the `<decision-matrix>` block") so cross-references survive flattening.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
