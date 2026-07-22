# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Project Purpose

This is a versioned collection of agents, skills, commands, and templates for AI coding assistants. Supports **Claude Code**, **OpenAI Codex CLI**, **Google Gemini CLI**, and **OpenCode**. Shared content is installed to all detected tools; tool-specific content goes only where it belongs.

## Vision & Mission

**Vision** — Make AI software development reliably autonomous. Concentrate human time *upstream* (brainstorming, design, judgment) and at thin verification gates (validation testing, exception handling); have agents execute implementation and machine-verifiable QA in the background, including overnight.

**Target operating ratio (aspirational, not yet measured)** — roughly **85% / 5% / 10%** of human time on brainstorming / troubleshooting escalations / validation testing, with a noticeably shorter idea-to-shippable cycle time than naked-LLM use.

**Prime directive** — *Get the human out of the agent-babysitting job.* When prioritizing work or resolving trade-offs in this repo, the tiebreaker question is: does this reduce human interventions per merged PR? Prefer the option that moves human time upstream (specs, judgment) or into thin verification gates; reject work that adds polish without reducing interventions.

**Mission** — Ship a portable discipline layer (agents, skills, commands, formulas, plugins) that makes that operating ratio achievable on any major AI coding assistant. The mechanism rests on five load-bearing commitments:

1. **Frontload human creativity & judgment** via rigorous brainstorming and a spec-readiness gate
2. **Make AI good at saying "no, not ready"** — bounce under-specified work back BEFORE implementation, with structured feedback on what is missing
3. **Substitute adversarial cross-model review** for human review wherever quality permits (RALF, foreign-CLI configs, codex adversarial review)
4. **Guardrail every completion claim with mechanical evidence** (completion gate, verify-checklist)
5. **Persist context** (work tickets, memories, formulas) so work survives compaction, agent handoff, and overnight runs

### Design principles for this repo

- **Code over Prose** — anything code can do better than agents, we move out of prose and into code helpers
- **Python/Go/Node over Bash** — thin shell script wrappers are fine; any logic that needs testing goes in Python, Go, or Node
- **Consolidate over conflict** — where plugins' assets overlap, merge the best-of-breed into the canonical source; avoid competing instructions
- **Beads is the work tracker** — use the `bd` CLI for task tracking directly; a higher-level `work` abstraction is planned but not yet in place
- **Flag confusing context** — if instructions, rules, or skills in this repo are conflicting or unclear, say so explicitly; cleaning up agent context is a first-class priority
- **Apply backpressure** — if a requested change doesn't clearly align with "cleaning house" or "advancing the vision", push back and ask how it fits before proceeding

## Project Architecture

It's simple: this project hosts "agent configuration" (and tools, helpers, etc.) under `src/` that are installed into the user space (e.g. `~/.claude/`, et. al) using the install script.  The installer will expand content into the target agents' config files, e.g. since only claude supports rules, the rules are expanded into codex's AGENTS.md file.  THUS whenever we're discussing making a change to a skill, an agent, a command, a rule, etc., your FIRST AND ONLY PLACE TO MAKE CHANGES is under the `src/**` folders' contents unless explicitly told otherwise.

**Implications:**

- **Always edit source, never deployed artifacts** — when the user asks to change a skill, agent, command, rule, or any other configuration artifact, edit the source file under `src/` (e.g., `src/user/.agents/skills/`, `src/user/.claude/rules/`). Files under `~/.claude/`, `~/.codex/`, `~/.gemini/`, etc. are deploy outputs and will be overwritten on the next installer run. If you catch yourself editing a path outside `src/`, stop and find the source equivalent.
- **No file-path citations in specs or prose** — Remember that the files that get written into the user space get used in OTHER projects.  Thus our assets CANNOT reference project-internal resources.  `INSTRUCTIONS.md.template` and all shared templates are flattened into per-tool assembled files at install time via `DYNAMIC-INCLUDE`. File-path citations (`INSTRUCTIONS.md > <section>`) are dead-ends after assembly. Always reference shared content by concept or block name (e.g., "the canonical decision matrix", "the `<decision-matrix>` block") so cross-references survive flattening.
- **NEVER run `scripts/install.sh` or `scripts/install.py` automatically** — only the user runs the installer, and only when they explicitly say so
- **Placement by capability-dependency, not asset type** — a new skill/agent/rule goes in the shared tree `src/user/.agents/` only if it works on every supported tool; anything that depends on tool-specific capabilities (e.g. Claude subagent orchestration, the Skill tool, AskUserQuestion, hooks) goes in that tool's tree (e.g. `src/user/.claude/skills/`)

## Repository Structure (current, not target state)

- `scripts/` - Installation and maintenance scripts
  - `install.sh` - Thin exec stub; delegates to the uv-managed Python installer (`packages/installer`) via `uv run`
  - `install.py` - Python entry point (`from installer.cli import main`); also invocable as `uv run python -m installer`
- `docs/guide/` - **User guide** for people *using* the deployed assets: how to install, configure a project, and run the opinionated agentic SDLC (`index`, `getting-started`, `configuration`, `sdlc-workflow`, `reference`)
- `docs/plans/` - Design documents for features in development
- `docs/specs/` - Design specifications (point-in-time proposals; date-prefixed filenames; status varies from draft through implemented)
- `docs/primers/` - Knowledge base of specific subjects to augment what you already know, or can get through your tools, about key primitives in this architecture (skills, agents, rules, commands, bead formulas, etc.)
- `docs/architecture/` - **High-level design (HLD) artifacts** for major subsystems: C4 diagrams (Context / Container / Component / Deployment), sequence diagrams, state machines, data-flow / persistence views. Grouped per subsystem in its own subfolder (e.g. `docs/architecture/pdlc-orchestrator/`). **Evergreen reference material** — amended in place as systems evolve; filenames are undated and describe content (e.g. `c4-l1-context.md`, `state-machine.md`). Distinct from `docs/specs/` (dated point-in-time proposals) and `docs/primers/` (prose explainers for the discipline layer itself). Each subfolder has an `index.md` orientation file referenced from its source design spec(s)
- `src/user/.agents/` - **Shared content** (copied into all detected tools)
  - `agents/` - Role-based agent definitions (frontmatter + instructions)
  - `skills/` - Methodology guides, some with supporting code/scripts
  - `rules/` - Tool-agnostic workflow rules (delegation, delivery, completion-gate, subagents, worktrees); same-name collisions append-merge
  - `INSTRUCTIONS.md.template` - Shared laws, constraints, workflow, orchestration
  - `AGENT-PERSONA.md.template` - Agent persona/personality template
  - `USER-PERSONA.md.template` - User persona template
- `src/user/.claude/` - **Claude-specific** content (copies to `~/.claude/`)
  - `commands/` - Slash command definitions (`.md`)
  - `skills/` - Claude-only skills (skills that depend on Claude-specific capabilities); cross-tool skills are sourced from `src/user/.agents/skills/`
  - `rules/` - Claude-specific rules (rules that only apply to Claude contexts); general rules are sourced from `src/user/.agents/rules/`
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
- `src/plugins/` - **Optional plugin content** (auto-detected and installed by the Python installer via a directory scan of `src/plugins/`; a plugin's rules deploy only when its tool is detected)
  - `beads/` - beads plugin: ships two rules — `beads.md` (bd CLI gotchas) and `discovered-work.md` (sibling-test placement). Gets a specialized adapter that also routes `~/.beads/`
  - `graphify/` - graphify plugin: the graphify discipline rule (shared)
  - `codex/` - codex plugin: the Codex routing rule (Claude-only)
- `packages/` - **Real Python packages** (standalone uv projects, each with its own `pyproject.toml`; not part of the installed config surface)
  - `installer/` - the installer engine that `scripts/install.sh` execs; CI-gated (`make ci-installer`)
  - `prgroom/` - deterministic PR-grooming CLI intended to eventually replace the `wait-for-pr-comments` and `reply-and-resolve-pr-threads` skills via `monitor-pr`; CI-gated (`make ci-prgroom`). **Not yet the active path** — `completion-gate.md` still routes PR-review monitoring through `wait-for-pr-comments` until the cutover ships (and the 2026-07-21 harness-rework spec proposes carving prgroom and deleting all three skills outright rather than completing this cutover — don't treat this line as settled). **Installed onto PATH by the installer** (`uv tool install`, receipt-tracked, pruned on retirement)
  - `workcli/` - the `work` facade CLI: quarantines the issue-tracker backend (bd) behind a stable JSON-envelope contract, twelve verbs over an injected `Backend` seam; CI-gated (`make ci-workcli`). Driven by the work-facade CLI contract spec (`docs/specs/2026-07-04-work-facade-cli-contract.md`). **Installed onto PATH by the installer** (`uv tool install`, receipt-tracked, pruned on retirement)
  - `pdlc/` - PDLC Orchestrator: the deterministic FSM engine intended to drive Objectives through the lifecycle. Early — happy-path tracer bullet only; not yet CI-gated
  - `holding-place/` - Idea pipeline + the Promote contract into the PDLC Orchestrator. Early; not yet CI-gated
- `project-config.toml` - part of the target architecture, contains key project-level configuration for how skills, agents, rules, etc. should behave for things like validation, agent delegation, etc.

Other notes:

- Most of the repo (config content under `src/`) is documentation and templates with no build step — changes there just follow existing formatting conventions per file type.
- **Exception — the packages under `packages/` are real Python code with mandatory quality gates.** `make ci` (the whole-repo gate CI enforces) runs `ci-installer` + `ci-prgroom` + `ci-workcli` + `lint-actions`. Before pushing a change under `packages/installer/` run `make ci-installer`; under `packages/prgroom/` run `make ci-prgroom`; under `packages/workcli/` run `make ci-workcli`. Each gate runs lint, format-check, typecheck, coverage, audit, and entry-verify. See the package's own `AGENTS.md` for its scoped workflow. (`packages/pdlc/` and `packages/holding-place/` are early and not yet wired into `make ci`.)

**Milestones** are `milestone`-type beads — no required fields, "contains no work itself" by convention. They anchor roadmap phases; child beads carry the actual work. Enumerate with `bd list --type milestone`.

Milestones form a sequential `blocks` chain: M0 → M1 → M2 → M3 → M4 → M5. PORT runs in parallel (no chain edge). Each milestone's `description` field is the canonical scope statement.

| ID                     | Status      | Milestone                                                                              |
| ---------------------- | ----------- | -------------------------------------------------------------------------------------- |
| `agents-config-wgclw`  | in_progress | **M0** — Discipline-layer rearchitecture (narrowed: land the in-flight epic-hygiene hardening, then close; PDLC-orchestrator design deferred) |
| `agents-config-abn9`   | in_progress | **M1** — Post-Fable operations: run the pipeline on Opus/Sonnet/cheap-model economics  |
| `agents-config-uxns2`  | open        | **PORT** — Portable discipline layer: home + work machine (parallel track)             |
| `agents-config-qn0g`   | open        | **M2** — Brainstorm-readiness gate                                                     |
| `agents-config-vaac`   | in_progress | **M3** — Worker fleet through PR autonomy, on cheap models with escalation ladders     |
| `agents-config-t142`   | open        | **M4** — Overnight autonomy: two-shift operating model + review feedback loop          |
| `agents-config-yf2ov`  | open        | **M5** — Post-MVP capabilities (frozen)                                                |

All milestones are P1. Work that maps to a milestone is a child of that milestone bead. A large share of the backlog carries status `deferred`: those beads were parked deliberately and are revivable with one command — do not treat a deferred bead as missing work or a stale queue.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)

