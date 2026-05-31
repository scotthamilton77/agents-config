# prgroom CLI — HLD Artifact Index

> **Source bead**: `agents-config-fca6.12`
> **Subsystem**: prgroom — PR-grooming CLI (`agents-config-fca6` epic)
> **Companion spec**: [`docs/plans/2026-05-12-prgroom-cli-design.md`](../../plans/2026-05-12-prgroom-cli-design.md) — the design these artifacts visualise
> **Glossary**: per-artifact short glossaries appear at the top of each file
> **Status**: under construction

## Glossary (subsystem-wide terms used across this artifact set)

| Term | Meaning |
|---|---|
| HLD | High-Level Design — evergreen reference material describing how a subsystem is meant to be structured and behave. This folder *is* the HLD set for prgroom. |
| C4 | A model for visualising software architecture in four levels (Context, Container, Component, Code); see [c4model.com](https://c4model.com). This folder uses L1, L2, L3, and Deployment. L4 (code) is intentionally absent. |
| prgroom | The PR-grooming CLI — a single static Go binary that absorbs the responsibilities of the legacy `wait-for-pr-comments` + `reply-and-resolve-pr-threads` skills. Phase-orchestration moves from agent prose into deterministic code. |
| Verb | A prgroom subcommand. The MVP verb set is `poll`, `cluster`, `fix`, `push`, `rereview`, `reply`, `resolve`, `resolve-escalated`, `wait`, `status`, `run`, `sweep`. |
| Phase | A position in prgroom's lifecycle for a single PR-grooming session. Each verb advances or operates within a phase; the run verb chains verbs to traverse phases. |
| Round | A single review-iteration loop: poll → cluster → fix → push → re-review → reply → resolve. Bounded by the §3.5 hard cap. |
| Disposition | The fix-orchestrator agent's per-comment classification: `FIX` (commit a code change), `SKIP` (acknowledge and dismiss), `ESCALATE` (defer to human). Per Section 5 of the source spec. |
| Quiescence | A definite end-state where no further bot or human reviewer activity is expected; prgroom may safely stop watching the PR. Defined in §4 of the source spec. |
| Contract A / Contract B | The two agent-dispatch contracts defined in §5. **A = `cluster`** (cheap grouping; local-first via ollama → claude haiku → codex-mini). **B = `fix`** (sonnet[1m] orchestrator that decides disposition AND implements). |
| `prsession.Store` | The state-persistence interface defined in §2 of the source spec. MVP default is the `file` adapter (`$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json`); a `memory` adapter exists for tests; the `bd` adapter is deferred to v2. **Naming-collision note:** this is a per-PR typed K/V store with locking — deliberately NOT named `WorkTracker` because PDLC orchestrator has a `WorkTracker` interface that abstracts a genuinely different concept (Objective registry with Discovery / CAS / fingerprinting). The two should not be conflated. |
| `EscalationSink` | The interface (Section 5) for surfacing items the fix orchestrator classified `ESCALATE`. Default is stderr; `bd` and `file` adapters available. |

Each artifact file in this folder carries its **own short glossary** at the top, listing the terms used in that specific file with one-line definitions.

## Purpose

This folder is the **high-level design (HLD) artifact set** for the prgroom CLI. It exists to fix the big-picture architecture before fca6.10 (the §3 implementation child) opens, so downstream implementation beads share a single mental model of the system boundary and lifecycle.

These artifacts are **evergreen reference material**: they describe how prgroom is meant to be structured and behave, and are amended in place as the design evolves. They are NOT point-in-time proposals — those live in `docs/plans/` and `docs/specs/` with date-prefixed filenames.

## Scope and non-scope

**In scope** for this artifact set:

- prgroom's place in its surrounding ecosystem (operator, scheduler, GitHub, agent CLIs, prsession state store)
- prgroom's internal containers and their responsibilities at MVP
- prgroom's runtime behaviour: one PR-grooming session's traversal through poll → cluster → fix → push → re-review → reply → resolve → wait, including the four canonical flows (happy, bot-silence, hard-cap, resumability)
- prgroom's lifecycle state machine: phase transitions per §3 and quiescence sub-states per §4
- prgroom's data ownership: what lives in the `prsession.Store`-backed state file vs the PR (GitHub) vs the git remote
- prgroom's deployment topology (single-host MVP; post-MVP markers)

**Out of scope** for this artifact set:

- Code-level (C4 L4) diagrams — C4 itself recommends against drawing this level
- Fully-drawn L3 component diagrams for every internal Go module — `internal/lifecycle` is fully drawn at L3 (it's the core of the binary); `internal/agent` and `internal/prsession` each have a **stub L3 file** establishing the home and expected components, to be filled in when their implementation children open
- The agent runtimes' internals (Claude Code, Codex CLI internals)
- Bead-lifecycle helpers, create-PR, merge, worktree cleanup — these stay in `finishing-a-development-branch` / `merge-and-cleanup` per the MVP scope decision in §1

## Reading order

Newcomers should read in this order; deep contributors may navigate freely.

1. **[C4 L1 — System Context](c4-l1-context.md)** — where does the `prgroom` CLI live? Who talks to it?
2. **[C4 L2 — Container](c4-l2-container.md)** — what is inside the `prgroom` system boundary?
3. **[Sequences](sequences.md)** — how does one PR-grooming session run? Four canonical flows (happy, bot-silence, hard-cap, resumability).
4. **[State Machine](state-machine.md)** — the six `PRPhase` values from §2, the §3.2 priority-cascade transitions, the §3.5 hard-cap exit, and the §4.1 quiescence predicate's hard gates
5. **[C4 L3 — Lifecycle](c4-l3-lifecycle.md)** — components inside the lifecycle container: the `runLocked` control flow at the verb level
6. **[Data View](data-view.md)** — what lives where: state file (PRGroomingState ER) + GitHub state + the status output and escalation event JSON contracts
7. **[C4 Deployment](c4-deployment.md)** — single-host MVP topology; scheduler integration; post-MVP markers

**L3 stub files** — placeholder homes for the remaining containers' component diagrams, to be filled in when their implementation children open:

- **[C4 L3 — Agent dispatch](c4-l3-agent-dispatch.md)** *(stub)*
- **[C4 L3 — PR session store](c4-l3-prsession.md)** *(stub)*

## Artifact synopsis

| File | Status | Synopsis |
|---|---|---|
| [`c4-l1-context.md`](c4-l1-context.md) | drawn | **C4 Level 1** — the `prgroom` CLI in its ecosystem: operator, scheduler (cron / `prgroom sweep`), GitHub (PR + reviews + threads), Claude/Codex/OpenCode agent CLIs, prsession state store (via `prsession.Store` interface), local state file |
| [`c4-l2-container.md`](c4-l2-container.md) | drawn | **C4 Level 2** — separately runnable / persistent units of `prgroom`: the `prgroom` binary (single short-lived Go process), the local state file (`prsession.Store` file-adapter storage), the local git worktree (where fix commits land), and the agent subprocess (forked per Contract A / Contract B dispatch). Internal Go modules (`internal/lifecycle`, `internal/prsession`, `internal/agent`, `internal/gh`, `internal/escalation`, etc.) are L3 **components** inside the binary, not L2 containers. |
| [`c4-l3-lifecycle.md`](c4-l3-lifecycle.md) | drawn | **C4 Level 3** (lifecycle) — components inside `internal/lifecycle`: the `runLocked` control flow with verb breakdown (`poll → cluster → fix → push → rereview → reply → resolve → wait`), showing `escalate_if_needed` and `request_human_review_if_needed` call sites |
| [`c4-l3-agent-dispatch.md`](c4-l3-agent-dispatch.md) | **stub** | **C4 Level 3** (`internal/agent`) — placeholder; expected components: Contract A (cluster) provider chain (ollama → haiku → codex-mini), Contract B (fix) sonnet[1m] orchestrator + EscalationSink wiring, per-contract config loader, token-usage JSONL emitter |
| [`c4-l3-prsession.md`](c4-l3-prsession.md) | **stub** | **C4 Level 3** (`internal/prsession`) — placeholder; expected components: `prsession.Store` protocol + adapter registry, file adapter (`$XDG_STATE_HOME/prgroom/...`), memory adapter (tests), transactional verb-level + run-aggregate commit model, schema-migration plumbing for `schema_version` |
| [`c4-deployment.md`](c4-deployment.md) | drawn | **C4 Deployment** — single-host MVP topology: prgroom binary on operator workstation, scheduler integration (cron / systemd timer / `prgroom sweep` loop), state file on local FS, gh CLI auth, agent-CLI bin presence. Explicit "multi-host POST-MVP" markers. |
| [`sequences.md`](sequences.md) | drawn | **Four sequence diagrams** covering the canonical flows: (1) happy path — push → review → fix → push → quiesce; (2) bot silence — Copilot doesn't engage → `review_start_timeout` auto-decline → quiesce; (3) hard-cap — 3 rounds without quiescence → human-gated + auto-add human-review-required label; (4) resumability — process crash mid-`waitLocked` → next invocation re-evaluates timeouts from stored UTC timestamps |
| [`state-machine.md`](state-machine.md) | drawn | **Phase graph + quiescence predicate**: the six §2 `PRPhase` values (`idle` / `awaiting-review` / `fixes-pending` / `quiesced` / `human-gated` / `merged`) with their §3.2-priority-cascade transition edges, the `Round` counter loop, the §3.5 hard-cap exit (with `EscalationSink` emit + §4.7 auto-label side-effect), the resurrection edges from `quiesced` and `human-gated` back into the loop, and a companion `flowchart` for the §4.1 quiescence predicate's 4 hard gates + idle timer |
| [`data-view.md`](data-view.md) | drawn | **State + contract data**: ER for `PRGroomingState` / `ReviewItem` / `Disposition` / `ReviewerState` / `QuiescenceState`; annotated JSON for the §4.6 `status` output, the Section 5 escalation events, and the §8 PR-memory schema skeleton; canonical-ownership boundaries (state-file vs PR vs git) |

## Conventions

- **Diagram notation**: Mermaid throughout, for native GitHub rendering. No SVG artifacts — `.md` files are the deliverable.
  - C4 set uses `C4Context` / `C4Container` / `C4Component` / `C4Deployment` syntax
  - Sequences use `sequenceDiagram`
  - State machine uses `stateDiagram-v2`
  - Data view uses `erDiagram` for entity relationships, `flowchart` and markdown tables for canonical-ownership boundaries, fenced JSON for flat contract objects (`status` output, escalation events)

- **PRPhase values** (`idle`, `awaiting-review`, `fixes-pending`, `quiesced`, `human-gated`, `merged`) are the canonical lifecycle phase identifiers throughout the artifact set — used verbatim in the state machine and data-view ER. The canonical reference is [Section 3.1](../../plans/2026-05-12-prgroom-cli-design.md). Note: Mermaid `stateDiagram-v2` requires valid identifiers (no hyphens), so the state machine diagram uses underscored node IDs (e.g., `awaiting_review`) aliased to labels matching the canonical hyphenated values.

- **C4 L4 (code) is intentionally absent.** C4 itself recommends against drawing this level for systems where the code is reasonably self-documenting; we follow that guidance.

## Source-spec coupling and rework risk

Diagrams in this folder are **derived artifacts**. The source of truth is `docs/plans/2026-05-12-prgroom-cli-design.md` Sections 1–8. Diagrams should cite the spec section they visualise (each file does so in its header) and be amended in place when the spec changes.

**Known pending rework — fca6.11 (Tick-based run model).** A sibling sub-design bead is open to rework `§3.3` (the `run` aggregate verb algorithm) and `§4.2` (`waitLocked` internals) toward a tick-based model where each tick = one cycle and the lock is held briefly per tick. When fca6.11 lands, the following artifacts will need re-drawing:

- `c4-l3-lifecycle.md` — the `runLocked` control flow becomes single-cycle
- `sequences.md` — flows 1 (happy path), 2 (bot-silence), 3 (hard-cap) all change shape (the `waitLocked` long-poll collapses to a per-tick predicate check)
- `state-machine.md` — phases stay, quiescence predicate stays, but the wait-edges become tick-driven
- `c4-deployment.md` — scheduler integration becomes the primary deployment story rather than a side note

Sections §1, §2, §4 (the *contract* of quiescence; the *mechanism* in §4.2 reworks), §5, §8 are not affected by the tick-model rework. fca6.12 reflects the current (blocking-model) spec; the rework will produce a paired commit to both the spec and these artifacts.

## How these artifacts should be used

- During **decomposition** of fca6 (the prgroom epic): every implementation child filer should read at minimum L1, L2, the happy-path sequence, and the state machine before drafting their bead's Spec, so the bead's scope claim aligns with the system boundary visible at L2.
- During **onboarding**: this is the first thing a new contributor (human or agent) reads to orient themselves in the prgroom subsystem.
- During **drift detection**: if implementation diverges from these diagrams without an amendment to them, that is a signal — either the diagrams need updating or the implementation has wandered. Prefer updating both as a paired commit.

## Provenance

Filed as `agents-config-fca6.12` under the `fca6` epic. This artifact set is the authoritative HLD for the prgroom CLI; it is referenced from the source design plan and will be cited from future implementation beads under fca6.
