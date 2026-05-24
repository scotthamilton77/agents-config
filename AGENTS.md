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
5. **Persist context** (work tickets, memories, formulas) so work survives compaction, agent handoff, and overnight runs

### New State - Ideas to keep us on track

Your job, agent, is to also keep these in mind as we continue to brainstorm and develop the details of the target architecture.  Eventually we can purge these from the project context once we fully capture this scope in the backlog.

#### Core Orchestration & Architecture
* **The Deterministic Code-First Orchestrator:**
    * Move orchestration logic out of Markdown (`SKILL.md`) and Bash scripts into a compiled/scripted language (Python/Go).
    * The orchestrator manages state transitions; agents are treated as isolated functions that read specs and write code.
* **WMS (Work Management System) Decoupling:**
    * Abstract the underlying tracker (Beads, GitHub, Jira) behind a CLI wrapper.
    * Execution agents must have ZERO awareness of the WMS. The Orchestrator handles all state updates and graph traversal.

#### The Mechanical Pipeline Gates
* **The "Agent-Ready" Thin Slice:**
    * A Unit of Work (UoW) is only ready when it is atomic and backed by machine-verifiable Acceptance Tests (ATs).
    * No judgmental/subjective criteria allowed in the execution phase.
* **The Red/Green Mechanical Gate:**
    * The transition from Test Writing to Implementation is gated by a deterministic runner (`npm test`, `pytest`).
    * Tests must compile against stubs and actively *fail* before implementation begins. No LLM "vibe checks" allowed for this gate.

#### Feedback Loops & Error Handling
* **The 3-Strike Circuit Breaker:**
    * Hardcode a limit on adversarial AI-to-AI review cycles. If an agent fails to pass the mechanical tests/reviews 3 times, the pipeline halts. Throw away the dirty git branch.
* **Dual Autopsy Agents (RCA):**
    * Triggered on a 3-Strike failure. Generates machine-readable facts, not excuses.
    * *Specification RCA Agent:* Looks for logical contradictions, missing context, and untestable criteria.
    * *Architecture Health RCA Agent:* Looks for tight coupling, legacy tech debt, and state contamination.
* **The Historical Linter (Pre-Mortem Agent):**
    * Reviews specs *before* execution, but only allowed to flag weaknesses if it can cite a specific, documented historical failure or ADR. Eliminates strawman hallucinations.

#### UX & Human-in-the-Loop
* **The "Cool Idea" Quarantine:**
    * A behavioral protocol for the interactive brainstorming agent. Actively isolates out-of-scope, complex ideas into an Icebox so the human can focus on the immediate thin slice without fear of losing the idea.
* **Visual AT Analysis Engine (Concept):**
    * Escape "bullet-point review hell" using spatial/visual node graphs (e.g., D3.js).
    * Map ATs against stable `CONTEXT.md` domains. Size by complexity, color by risk.
    * Use multimodal AI to analyze the topological graph and highlight architectural violations instantly.
* **Dreaming / Subconscious Backlog Process (Concept):**
    * Verbatim (Scott, 2026-05-17, while designing the PDLC state machine in `agents-config-wgclw.1`): a background process that periodically scans the backlog looking for new connections, broken connections, stale connections, between work items. Consider this a "dreaming" process or subconscious process of strengthening edges between memory nodes.
    * Purpose: supports topic-correlated Idea resurfacing (option C from the holding-place exit-condition tradeoff) AND sequencing recommendations during "what's next to work on" pulls — e.g. "you want to work on X, but Y might be a blocking dependency for X."
    * Provenance backreference: captured live during the brainstorm of `agents-config-wgclw.1` (PDLC State Machine Design); parked here pending an official Capture surface.

#### Architecture and Objectives
* **Architecture Context:**
  * A project needs a high-level architecture (CONTEXT.md, HLD artifacts (TBD)) and every objective must be linkable to a specific part of the architecture.
* **Architecture Heatmap:**
  * Given an HLD, we should be able to show the work associated with the HLD components (at whatever state they are in) to show which parts are theoretical, which are planned, which are done, and to whatever degree.  This can help in prioritization/bucketing, but also allows us to maintain focus on specific components without losing track of the rest of the architecture, and perform audits to see where we're veering off MVP or tracer bullet goals.

### Current state — FAILED work in progress

The architecture has run into a problematic ocean of complexity and inverted engineering where agents are doing the wrong things (things algorithms should be doing).  We're presently in a REDESIGN phase where much of the old and suspect architecture has been pushed under the `archive/` folder to serve as references until we don't need them anymore.  You should NOT peek in there unless/until you need to.  (Don't let its contents poison your understanding of current and future state).

That means that the current code architecture is a work in progress that is being cleaned up with the following goals in mind:

- **Code over Prose** - Anything code can do better than agents, we're moving out of prose and into code helpers
- **Python over Bash** - Thin shell script wrappers are fine but any logic that needs good testing needs to be in Python
- **Amalgams over Conflicts** - There are currently competing priorities in certain plugins that contribute to context rot - we'll be consolidating "best of breed" from plugins' skills and other assets such as superpowers, pollock, karpathy, and so on
- **Work vs beads** - While we'll continue to use the beads infrastructure (and possibly plugin) we'll be taking a step back from making that a first class citizen of this project's architecture, placing a "work" abstraction in front of it - end state is that beads is quarantined behind our own CLI

### Implications for agents working in *this* repo

- You'll still use beads directly for the time being until we get our work abstraction in place
- The current backlog of beads is meaningful in a historic sense, but we'll be cleaning that up substantially over time
- I need YOUR help (talking to you, agent!) to point out confusion or ambiguity in your context and where it's coming from - job #1 is to clean that up and give you an environment that's useful, not confusing - TELL ME WHAT MAKES THINGS HARDER THAN THEY SHOULD BE
- The goals of the architecture are still valid / remain, but right now we're prioritizing getting the house in order to make it possible to accrete work toward that 85/5/10 goal. So while I'll need you (the agent) to point out what's in the way of this now, I also want you to watchdog what I'm asking you to do and apply backpressure where it's not clear how what I'm asking for is aligned with cleaning house or paving the road to the vision.

## Project Architecture

It's simple: this project hosts "agent configuration" (and tools, helpers, etc.) under `src/` that are installed into the user space (e.g. `~/.claude/`, et. al) using the install script.  The installer will expand content into the target agents' config files, e.g. since only claude supports rules, the rules are expanded into codex's AGENTS.md file.  THUS whenever we're discussing making a change to a skill, an agent, a command, a rule, etc., your FIRST AND ONLY PLACE TO MAKE CHANGES is under the `src/**` folders' contents unless explicitly told otherwise.

**Implications:**

- **Always edit source, never deployed artifacts** — when the user asks to change a skill, agent, command, rule, or any other configuration artifact, edit the source file under `src/` (e.g., `src/user/.agents/skills/`, `src/user/.claude/rules/`). Files under `~/.claude/`, `~/.codex/`, `~/.gemini/`, etc. are deploy outputs and will be overwritten on the next `install.sh` run. If you catch yourself editing a path outside `src/`, stop and find the source equivalent.
- **No file-path citations in specs or prose** — Remember that the files that get written into the user space get used in OTHER projects.  Thus our assets CANNOT reference project-internal resources.  `INSTRUCTIONS.md.template` and all shared templates are flattened into per-tool assembled files at install time via `DYNAMIC-INCLUDE`. File-path citations (`INSTRUCTIONS.md > <section>`) are dead-ends after assembly. Always reference shared content by concept or block name (e.g., "the canonical decision matrix", "the `<decision-matrix>` block") so cross-references survive flattening.
- **NEVER run `install.sh` (or, when it is available, install.py) automatically** — only the user runs the installer, and only when they explicitly say so

## Repository Structure (current, not target state)

- `scripts/` - Installation and maintenance scripts
  - `install.sh` - Multi-tool installer with auto-detection, `--dry-run`, `--tools=`/`--plugins=` overrides, and `--prune`/`--prune-only` for removing orphaned items not in the source
- `docs/plans/` - Design documents for features in development
- `docs/specs/` - Design specifications for implemented features (point-in-time proposals; date-prefixed filenames)
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
  - `rules/` - Claude-specific workflow rules (`claude-sandbox.md`, `claude-to-codex-routing.md`); general rules are sourced from `src/user/.agents/rules/`
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
- `project-config.toml` - part of the target architecture, contains key project-level configuration for how skills, agents, rules, etc. should behave for things like validation, agent delegation, etc.

Other notes:

- No build system, tests, or linting - this is pure documentation
- Changes should follow existing formatting conventions in each file type

## Project Milestones (current, not target)

**Milestones** are `milestone`-type beads — no required fields, "contains no work itself" by convention. They anchor roadmap phases; child beads carry the actual work. Enumerate with `bd list --type milestone`.

Milestones form a sequential `blocks` chain: M0 → M1 → M2 → M3 → M4. Each milestone's `description` field is the canonical scope statement.

| ID | Status | Milestone |
|----|--------|-----------|
| `agents-config-wgclw` | open | **M0** — Discipline-layer rearchitecture: scripts own determinism, skills own judgment |
| `agents-config-abn9` | in_progress | **M1** — Stabilize, finish in-flight, ship immediate accelerators |
| `agents-config-qn0g` | open | **M2** — Brainstorm-readiness gate |
| `agents-config-vaac` | in_progress | **M3** — Worker fleet through PR autonomy |
| `agents-config-t142` | open | **M4** — Overnight autonomy |

All milestones are P1. Work that maps to a milestone is a child of that milestone bead.

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

- Use `bd` for ALL discovered work tracking — *except for in-session planning*, do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol

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
