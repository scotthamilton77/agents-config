# PDLC Orchestrator — HLD Artifact Index

> **Source bead**: `agents-config-wgclw.2.1`
> **Subsystem**: PDLC Orchestrator (`agents-config-wgclw.2` and descendants)
> **Companion specs**:
> - `docs/specs/2026-05-23-pdlc-orchestrator-core-design.md` — the orchestrator core design these artifacts visualise
> - `docs/specs/2026-05-19-pdlc-state-machine-design.md` — the FSM companion
>
> **Glossary**: `CONTEXT.md` (canonical); per-artifact short glossaries appear at the top of each file
> **Status**: under construction

## Glossary (project-wide terms used across this artifact set)

| Term | Meaning |
|---|---|
| HLD | High-Level Design — evergreen reference material describing how a subsystem is meant to be structured and behave. This folder *is* the HLD set for the PDLC Orchestrator. |
| C4 | A model for visualising software architecture in four levels (Context, Container, Component, Code); see [c4model.com](https://c4model.com). This folder uses L1, L2, L3, and Deployment. L4 (code) is intentionally absent. |
| PDLC | Product Development Lifecycle — the FSM the Orchestrator drives Objectives through. The canonical state list lives in the [orchestrator core design's Lifecycle Stage Constants table](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#lifecycle-stage-constants). |
| Objective | The unified primitive the Orchestrator tracks from `CANDIDATE_UOW` to a terminal lifecycle stage. See `CONTEXT.md > Objective`. |
| Idea | The pre-Objective primitive in the Holding Place pipeline. See `CONTEXT.md > Idea`. |
| Lifecycle Stage | The Orchestrator-owned position of an Objective in the FSM (e.g. `CANDIDATE_UOW`, `IMPLEMENTING`, `MERGED`). Named English constants only; see [Conventions](#conventions) below. |
| Stub | A placeholder file with structure but no diagram yet — to be filled in when the corresponding implementation child opens and has ratified design to draw against. |

Each artifact file in this folder carries its **own short glossary** at the top, listing the terms used in that specific file with one-line definitions. This avoids forcing readers to context-switch back to a central glossary mid-diagram.

## Purpose

This folder is the **high-level design (HLD) artifact set** for the PDLC Orchestrator. It exists to cement the big-picture architecture before any sibling implementation child of `wgclw.2` opens, so decomposition and downstream implementation beads share a single mental model.

These artifacts are **evergreen reference material**: they describe how the orchestrator is meant to be structured and behave, and they are amended in place as the design evolves. They are NOT point-in-time proposals — those live in `docs/specs/` with date-prefixed filenames.

## Scope and non-scope

**In scope** for this artifact set:

- The orchestrator's place in its surrounding ecosystem (developer, work tracker, agents, git, CI, Holding Place, project-config)
- The orchestrator's internal containers and their responsibilities
- The orchestrator's runtime behaviour: tick cycle, Objective happy-path traversal, lifecycle state machine
- The orchestrator's data ownership: what lives in the tracker vs the OrchestratorStateRepo vs the filesystem
- The orchestrator's deployment topology (single-host MVP; post-MVP markers)

**Out of scope** for this artifact set:

- Code-level (C4 L4) diagrams — C4 itself recommends against drawing this level
- Fully-drawn component diagrams for every container — the tick loop is fully drawn at L3; WorkTracker adapter, JobSupervisor, and OrchestratorStateRepo each have their own **stub L3 file** establishing the home and expected components, to be filled in when their respective implementation children open
- Persona-internal flows (Test-Author, Implementer, Reviewer, RCA) — those belong to wgclw.3 / wgclw.4 / wgclw.6 HLD sets in their own subfolders

## Reading order

Newcomers should read in this order; deep contributors may navigate freely.

1. **[C4 L1 — System Context](c4-l1-context.md)** — where does the `pdlc` CLI live? Who talks to it?
2. **[C4 L2 — Container](c4-l2-container.md)** — what is inside the `pdlc` system boundary?
3. **[Sequences](sequences.md)** — how does one tick run? How does an Objective traverse the happy path?
4. **[State Machine](state-machine.md)** — the full lifecycle stage graph: retries, autopsy routing, terminals
5. **[C4 L3 — Tick Loop](c4-l3-tick-loop.md)** — components inside the tick container
6. **[Data View](data-view.md)** — what lives where: tracker vs OrchestratorStateRepo vs filesystem
7. **[C4 Deployment](c4-deployment.md)** — single-host MVP topology; post-MVP markers

**L3 stub files** — placeholder homes for the remaining containers' component diagrams, to be filled in when their implementation children open:

- **[C4 L3 — WorkTracker adapter](c4-l3-worktracker-adapter.md)** *(stub)*
- **[C4 L3 — JobSupervisor](c4-l3-jobsupervisor.md)** *(stub)*
- **[C4 L3 — OrchestratorStateRepo](c4-l3-state-repo.md)** *(stub)*

## Artifact synopsis

| File | Status | Synopsis |
|---|---|---|
| [`c4-l1-context.md`](c4-l1-context.md) | drawn | **C4 Level 1** — the `pdlc` CLI in its ecosystem: developer/operator, `bd` (and the WorkTracker adapter boundary), git, CI, Claude/Codex/Gemini agents, Holding Place (peer service), project-config files |
| [`c4-l2-container.md`](c4-l2-container.md) | drawn | **C4 Level 2** — internal containers of the `pdlc` system: tick loop, OrchestratorStateRepo (Dolt-backed sidecar), WorkTracker adapter (bd-bound), JobSupervisor, Worker subprocess, Worktree filesystem, project-config loader |
| [`c4-l3-tick-loop.md`](c4-l3-tick-loop.md) | drawn | **C4 Level 3** (tick loop) — components inside the tick loop container: DISCOVER, RECONCILE, REAP, DISPATCH, PERSIST, plus Lease manager, CAS predicate evaluator, Pre-strike triage classifier, Sizing Gate calculator |
| [`c4-l3-worktracker-adapter.md`](c4-l3-worktracker-adapter.md) | **stub** | **C4 Level 3** (WorkTracker adapter) — placeholder; expected components: protocol-method groupings, bd CLI invocation, CAS predicate computation, fingerprint computation, error translation, Discovery marker management |
| [`c4-l3-jobsupervisor.md`](c4-l3-jobsupervisor.md) | **stub** | **C4 Level 3** (JobSupervisor) — placeholder; expected components: lease lifecycle, heartbeat reporter, deadline enforcer, terminal-status collector, capture handles, cancellation handler, crash-recovery roll-forward |
| [`c4-l3-state-repo.md`](c4-l3-state-repo.md) | **stub** | **C4 Level 3** (OrchestratorStateRepo) — placeholder; expected components: schema migrations, per-table DAOs, branch-checkpoint mechanism, CAS predicate API, read-only-cache fallback, retention policy |
| [`c4-deployment.md`](c4-deployment.md) | drawn | **C4 Deployment** — single-host MVP topology: CLI process, cron trigger, Dolt sidecar volume, worker subprocesses, worktree filesystem, tracker store. Explicit "multi-host POST-MVP" annotations |
| [`sequences.md`](sequences.md) | drawn | **Two sequence diagrams**: (a) one tick cycle (DISCOVER → RECONCILE → REAP → DISPATCH → PERSIST) with concrete actors; (b) Objective happy path (Idea → MERGED) with worker dispatches at each gate |
| [`state-machine.md`](state-machine.md) | drawn | **Full lifecycle stage graph**: retry edges, 3-strike → `AUTOPSY`, Container-decomposition divergence (Decomposed Container as passive aggregator), terminal states (`MERGED` / `KILLED` / `PARKED`); `needs_reconcile` shown as a flag, not a state |
| [`data-view.md`](data-view.md) | drawn | **What lives where**: tracker domain vs OrchestratorStateRepo vs filesystem; marker semantics; CAS predicate flow; canonical-ownership boundaries |

## Conventions

- **Diagram notation**: Mermaid throughout, for native GitHub rendering.
  - C4 set uses `C4Context` / `C4Container` / `C4Component` / `C4Deployment` syntax
  - Sequences use `sequenceDiagram`
  - State machine uses `stateDiagram-v2`
  - Data view uses `flowchart` or markdown tables as appropriate

- **Lifecycle Stage Constants** appear as **named English constants** throughout — `CANDIDATE_UOW`, `AGENT_WORTHY`, `DECOMPOSE`, `EXECUTABLE_READY`, `CONTAINER_DECOMPOSED`, `TEST_AUTHORING`, `IMPLEMENTING`, `REVIEWING`, `PR_VALIDATION`, `PR_HUMAN_HOLD`, `MERGING`, `AUTOPSY`, `MERGED`, `KILLED`, `PARKED`. Numeric stage IDs (3, 4, 5, 6, 6′, 7-10C, 11) appear only as low-attention ordering hints in tables. The canonical reference is the [Lifecycle Stage Constants table in the orchestrator core design spec](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#lifecycle-stage-constants).

- **C4 L4 (code) is intentionally absent.** C4 itself recommends against drawing this level for systems where the code is reasonably self-documenting; we follow that guidance.

## How these artifacts should be used

- During **decomposition** of `wgclw.2`: every implementation child filer should read at minimum L1, L2, the tick-cycle sequence, and the state machine before drafting their bead's Spec, so the bead's scope claim aligns with the system boundary visible at L2.
- During **onboarding**: this is the first thing a new contributor (human or agent) reads to orient themselves in the PDLC subsystem.
- During **drift detection**: if implementation diverges from these diagrams without an amendment to them, that is a signal — either the diagrams need updating or the implementation has wandered. Prefer updating both as a paired commit.

## Provenance

Filed as `agents-config-wgclw.2.1` under `wgclw.2` (PDLC Orchestrator Core & Foundations). This artifact set is the authoritative HLD for the PDLC Orchestrator; it is referenced from the core design spec at [§ Happy-path flowchart](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#happy-path-flowchart).

A follow-up bead (`agents-config-zzsv8`) tracks whether to promote the orchestrator core design from its dated location in `docs/specs/` to an evergreen location in this folder. That decision is intentionally deferred — it affects future architecture sets across all PDLC epics, not just this one.
