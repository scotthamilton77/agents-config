# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Project Purpose

A versioned collection of agents, skills, commands, and templates for AI coding assistants. Supports **Claude Code**, **OpenAI Codex CLI**, **Google Gemini CLI**, and **OpenCode**. Shared content is installed to all detected tools; tool-specific content goes only where it belongs.

## Harness Rework (active — read this first)

The harness is being rebuilt. Until the rework milestone closes (charter AC9), orient new work against these sources, in this order:

1. `docs/specs/2026-07-21-harness-rework-way-forward.md` — the canonical charter: all decisions (D1–D20), acceptance criteria (AC1–AC9), the ordered slice plan (S0–S10), and the zero-based user AGENTS.md draft (Appendix A). If you read only one file, read this one.
2. `work show agents-config-9k9` — where "where are we right now" lives: the milestone carries the charter pointer, records facade gaps in its notes, and its children are the live status of what is minted, in flight, and done. The charter deliberately tracks no progress.
3. `SAVEPOINTS/2026-07-20-harness-findings-handoff.md` — the evidence behind the charter's decisions. Read when a decision seems underjustified.
4. `docs/specs/2026-07-22-workcli-completion-s2.md` — the S2 child spec, and the worked example of the per-slice pattern (child spec → per-slice ACs → implement).

Standing implications while the rework runs:

- Where any deployed rule, skill, or doc (including this file) contradicts the charter, the charter wins — and flag the contradiction explicitly so it gets fixed.
- Address the tracker through the `work` facade (D11). Fall back to `bd` only when the facade cannot express the operation, and record each fallback as a facade gap in a note on `agents-config-9k9`.
- New harness work enters only as a child of the milestone, carrying an admission record: what it prevents or provides, what it costs, and what observation would remove it (D16/D20).
- Any proposal to add a rule/skill/command/agent to `src/`, or to lift one out of `archive/`, runs through the `admit-request` skill — a project-scoped gate, not a deployed asset. Its default verdict is DECLINE; there is no grandfathering.
- **`archive/` is not live.** Nothing under it describes current behaviour — do not follow it, cite it as a contract, or invoke a skill found there. If a workflow you need exists only in `archive/`, that is the signal to escalate, not to reinstate it by hand.
- **The admission gate decides what deploys, not the folder.** The installer drops any rule/skill/command/agent whose front matter lacks a complete `admission:` record, wherever it sits — plugin trees included. What the gate admits, it sanitizes: the `admission:`/`claims:` front matter and the provenance comment are repo-side bookkeeping, stripped from the deployed bytes. Write them for this repo's reader, not the downstream agent's.
- **Presence in `src/` is not evidence of deployment**, and neither is an admission record — an admitted artifact can still fail a mechanical staging check and ship nothing. Before telling a user or a subagent that a skill, rule, or command is available, list the tool's own config directory and confirm it landed.

### How work ships here

This is the whole delivery contract:

1. Enter the work in the tracker via `work` verbs, as a child of `agents-config-9k9`, with an admission record. Installer work also carries the `install` label; nest it under an install epic beneath the owning milestone.
2. Implement on a worktree branch; never commit to the default branch.
3. Verify mechanically before claiming anything. For `packages/**`, and for any skill under `src/` that ships its own tests, that is `make ci` — read the `ci` target in the `Makefile` for its current membership, and note that a single package's gate is not the whole-repo gate. Run it from the root of the tree you are working in: the `Makefile` `cd`s relative to the invoking directory, so a gate run from the main checkout while you are on a worktree branch reports green on code you did not change. Run the gate standalone and read its exit status — never pipe it into a `grep && commit` chain, where the pipeline's status is the grep's and a red gate ships. For prose-only changes, state what you checked and how.
4. Open a PR and address review to quiescence. Every item gets a disposition in your own inventory; only items that change the code get a reply on the PR. Bookkeeping and meta comments are dispositioned silently — a thread of "no action required" replies is noise the next reader has to wade through.
5. **Merge only on an explicit human instruction.** No rule-based merge policy is configured here, no implementation of one is deployed, and the repository ruleset requires an approving review that no configured reviewer submits — see `agents-config-9k9.23`. The shared hard-lines permit merging under "a configured rule-based policy"; that clause has nothing here to match. If you believe it does, read `project-config.toml`'s `[merge-policy]` before acting on it, and read anything commented out there as future work rather than permission.

## Vision & Mission

**Vision** — Make AI software development reliably autonomous. Concentrate human time *upstream* (brainstorming, design, judgment) and at thin verification gates (validation testing, exception handling); have agents execute implementation and machine-verifiable QA in the background, including overnight.

**Target operating ratio (aspirational, not yet measured)** — roughly **85% / 5% / 10%** of human time on brainstorming / troubleshooting escalations / validation testing, with a noticeably shorter idea-to-shippable cycle time than naked-LLM use.

**Prime directive** — *Get the human out of the agent-babysitting job.* When prioritizing work or resolving trade-offs in this repo, the tiebreaker question is: does this reduce human interventions per merged PR? Prefer the option that moves human time upstream (specs, judgment) or into thin verification gates; reject work that adds polish without reducing interventions.

**Mission** — Ship a portable discipline layer that makes that operating ratio achievable on any major AI coding assistant. The mechanism rests on five load-bearing commitments:

1. **Frontload human creativity & judgment** via rigorous brainstorming and a spec-readiness gate
2. **Make AI good at saying "no, not ready"** — bounce under-specified work back BEFORE implementation, with structured feedback on what is missing
3. **Substitute adversarial cross-model review** for human review wherever quality permits
4. **Guardrail every completion claim with mechanical evidence**
5. **Persist context** (work items, memories) so work survives compaction, agent handoff, and overnight runs

Commitments 3 and 4 have no deployed implementation right now; the charter's slice plan owns what replaces them. Do not go looking for the retired one.

### Design principles for this repo

- **Code over Prose** — anything code can do better than agents, we move out of prose and into code helpers
- **Python/Go/Node over Bash** — thin shell script wrappers are fine; any logic that needs testing goes in Python, Go, or Node
- **Consolidate over conflict** — where assets overlap, merge the best-of-breed into the canonical source; avoid competing instructions
- **The `work` facade is the tracker interface** — address the tracker through `work` verbs (charter D11); the harness never speaks `bd`. Fall back to `bd` only for operations the facade can't express, and record each fallback as a facade gap (note on `agents-config-9k9`)
- **Flag confusing context** — if instructions, rules, or skills in this repo are conflicting or unclear, say so explicitly; cleaning up agent context is a first-class priority
- **Apply backpressure** — if a requested change doesn't clearly align with "cleaning house" or "advancing the vision", push back and ask how it fits before proceeding

## Project Architecture

This project hosts agent configuration under `src/`, which the install script deploys into user space (`~/.claude/`, `~/.codex/`, `~/.gemini/`, `~/.config/opencode/`). **When changing a skill, agent, command, rule, or any other configuration artifact, `src/` is your first and only place to make changes** unless explicitly told otherwise.

**Implications:**

- **Always edit source, never deployed artifacts** — files under `~/.claude/`, `~/.codex/`, `~/.gemini/` and `~/.config/opencode/` are deploy outputs and are overwritten on the next installer run. If you catch yourself editing a path outside `src/`, stop and find the source equivalent.
- **No file-path citations in deployed prose** — deployed assets get used in OTHER projects, so they cannot reference this project's resources. Shared templates are flattened into per-tool assembled files at install time via `DYNAMIC-INCLUDE`, which makes a file-path citation a dead end after assembly. Reference shared content by concept or block name (e.g. "the shared decision rules", "the `<decisions>` block") so cross-references survive flattening.
- **NEVER run `scripts/install.sh` or `scripts/install.py` automatically** — only the user runs the installer, and only when they explicitly say so
- **Placement by capability-dependency, not asset type** — an artifact goes in the shared tree `src/user/.agents/` only if it works on every supported tool; anything depending on tool-specific capabilities (Claude subagent orchestration, the Skill tool, AskUserQuestion, hooks) goes in that tool's tree

## Repository Structure (current, not target state)

- `scripts/` — installer entry points and maintenance scripts. `install.sh` is a thin exec stub delegating to the uv-managed Python installer in `packages/installer`; `install.py` is the Python entry point. See `scripts/AGENTS.md`.
- `src/` — **the deployed surface.** Everything installed into user space is authored here.
  - `src/user/.agents/` — shared content, staged into every active tool: `skills/`, `rules/`, and `USER-CORE.md.template` (the zero-based laws, decision matrix, hard lines, and conventions, D17). See `src/user/.agents/AGENTS.md` for the install model and the name-collision rules.
  - `src/user/.claude/` — Claude-only: `skills/`, `rules/`, `hooks/`, `AGENTS.md.template`, `CLAUDE.md.template`, `settings.json.template`
  - `src/user/.codex/`, `src/user/.gemini/`, `src/user/.opencode/` — per-tool instruction templates; OpenCode additionally carries `opencode.jsonc.template` and gets a flat, dynamically-built instruction file rather than `@` includes
  - `src/plugins/` — optional plugin content, auto-detected by a directory scan. A plugin's content deploys only when its tool is detected **and** the artifact clears the admission gate.
  - Each rules directory carries its own `AGENTS.md` stating what currently lives there; read it rather than inferring from the folder's contents.
- `archive/` — retired content mirroring the live tree's shape (`archive/src/user/**`, `archive/docs/**`). **Historical only — never a behavioural contract.** Read it to recover an idea; do not copy a path back into `src/` without an admission record.
- `docs/`
  - `guide/` — user guide for people *running* the deployed assets: install, configure a project, run the agentic SDLC
  - `specs/` — dated point-in-time design proposals; status varies from draft through implemented. A spec describes its full intent, and partial per-PR implementation is expected — a spec that describes code nobody has written yet is working as designed, not a defect to file or annotate.
  - `architecture/` — evergreen HLD artifacts (C4 levels, sequence diagrams, state machines, data-flow views), grouped per subsystem with an `index.md` orientation file. Amended in place; filenames are undated and describe content.
  - `primers/` — explainers for the key primitives of this architecture (skills, agents, rules, commands, formulas)
  - `plans/`, `adr/`, `reference/`, `prototypes/`, `beads/` — supporting material
- `packages/` — standalone uv projects; **not** part of the installed config surface.
  - `installer/` — the installer engine that `scripts/install.sh` execs
  - `workcli/` — the `work` facade CLI: quarantines the issue-tracker backend behind a stable JSON-envelope contract. Driven by `docs/specs/2026-07-22-workcli-completion-s2.md`, which supersedes the 2026-07-04 work-facade contract spec where they conflict.
  - `grind/` — the event-sourced grind runtime: event schema, FSM fold, and the `grind` CLI that D14 nominates as the pipeline executor loop
  - `prgroom/` — PR-grooming CLI. Per charter D13 it is **carved, not finished** (slice S8).
  - `executor/` — the decision layer above grind and the `work` facade: the closed pairing table that turns one executor verb into one runtime event and at most one tracker verb. Driven by `docs/specs/2026-07-25-executor-seam-s9-tier1.md`. There is no dispatch loop — it answers what a verb pairs with, not when to run it.
  - `gitclean/` — surveys this repository's worktrees and branches, sweeps only what it can prove is merged, and reports everything else with the measurement that stopped it. Merge evidence resolves in tiers rather than trusting `git branch --merged`, which under squash merges is wrong in both directions. It concludes one thing — is this provably merged? — and a bare sweep takes only targets that clear that plus five measured checks; a target named on the command line is not re-adjudicated at all, so naming one is an authorisation and the caller owns the consequence. That boundary is now settled, so it ships: it is on PATH and the `clean-up-git` skill drives it.
  - `pdlc/`, `holding-place/`, `vizsuite/`, `contracts/` — earlier-stage packages
  - `workcli`, `prgroom`, `grind`, `executor` and `gitclean` are the packages installed onto PATH (`uv tool install`, receipt-tracked, pruned on retirement), landing as the `work`, `prgroom`, `grind`, `executor` and `gitclean` commands; `CLI_PACKAGES` in `packages/installer/src/installer/core/clis.py` holds that list. Being gated by `make ci` is not what earns a place on it — `vizsuite` is gated and stays off. Most packages carry their own `AGENTS.md` with a scoped workflow — read it before changing that package.
- `project-config.toml` — project-level configuration, and the convention is that **a commented-out key is future work nothing reads**, not a live setting. Uncomment one only in the change that deploys its reader. `.critical-paths` follows the same convention and currently selects nothing.
- `.beads/` — the tracker's storage layer. Addressed through the `work` CLI, never `bd` and never by hand; see `.beads/AGENTS.md`.

Other notes:

- Most content under `src/` is documentation and templates with no build step — changes there follow existing formatting conventions per file type. A skill that ships its own tests is the exception: `content-tests` is the single gate over them, and it runs every `.py`/`.js`/`.sh` suite it finds under `src/`, requires each shipped script to have a paired suite, and fails a suite that exits 0 without printing the clean-pass marker its runner declares — an empty run and a swallowed failure both exit 0 and would otherwise read as green. Those suites are gated code, not prose. `src/` is also measured against the admission bar and its token caps by `content-lint`, which stages the real tree for every tool and plugin and reports the always-on and per-skill numbers on a pass, so drift is visible before the cliff. The two gates read `src/` differently on purpose — `content-lint` measures the *staged* tree, because the bar and the budget are properties of what deploys — and it fails on a directory staging never reads and nothing declares. `.installignore` is where a directory declares itself source-side, so an edit there changes what this gate measures. Neither `src/` gate invokes the installer.
- **`packages/` is real Python code with mandatory quality gates.** `make ci` is the whole-repo gate CI enforces; each gated package also has its own `ci-<package>` target running lint, format-check, typecheck, coverage, audit, and entry-verify. Read the `Makefile` for which packages are currently in `ci` — not every package under `packages/` is wired in.

## graphify

`graphify-out/` is untracked. When it is there, it is a snapshot someone built by hand at
some past moment — not an index that follows the tree. A graph built before a refactor
still names the files that refactor deleted, so verify anything it reports against the
working tree before asserting it. `graphify update .` builds a fresh one in a few seconds
if you want it, and running it from a worktree is fine: everything it writes, including
`.graphify_root`, lands inside that worktree's own `graphify-out/`, which is untracked
and disappears with the worktree. Never stage `graphify-out/` into a branch.

## Communication Style

In conversations with the user, keep your responses concise and don't over-explain; let 
the user ask for more detail rather than offering it proactively. BLUF - bottom line up 
front.  Don't assume the user will recognize work by work-id, document sections by section
number, etc.  The user needs help connecting dots sometimes, so it's ok to use short
reminders, e.g. `xjc2.4 (auth feature epic)`.
