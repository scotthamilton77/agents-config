# PDLC Orchestrator — C4 Level 3: OrchestratorStateRepo Components (STUB)

> **Up**: [index](index.md)
> **Sibling L3**: [Tick Loop](c4-l3-tick-loop.md) (fully drawn)
> **Source bead**: `agents-config-wgclw.2.1`
> **Status**: **STUB — not yet drawn**

## Why this file exists

The OrchestratorStateRepo is the [C4 L2 data-store container](c4-l2-container.md) holding everything the Orchestrator is canonical for: lifecycle stages, strike counts, transition log, sessions, leases, sidecar dependencies, and the Discovery marker. Its internal component breakdown — schema migrations, per-table DAOs, branch-checkpoint mechanism, CAS API surface — belongs at L3.

This file is a **placeholder home** for that diagram. It will be filled in when the OrchestratorStateRepo schema and DAO implementation child (under `wgclw.2`) opens. Establishing the home now means future contributors don't have to invent folder structure mid-stride; drafting the components prematurely would lock in schema decisions the implementation child has not ratified.

## Glossary

| Term | Meaning |
|---|---|
| Dolt | A SQL database with git-style branching, commits, and merges — the chosen storage backend for OrchestratorStateRepo |
| Per-tick branch checkpoint | A Dolt branch commit performed at the end of every successful tick, enabling `dolt log` replay for crash recovery |
| DAO (Data Access Object) | Typed Python module that mediates between in-process orchestrator code and the SQL store; one DAO per table |
| CAS (Compare-And-Swap) | Concurrency control: write under a version predicate (e.g. row-version); mismatch aborts the transition |
| Sidecar | A store the orchestrator owns that holds data not yet promoted to the WorkTracker protocol (MVP-scoped) |

## Expected components (pending design ratification)

When this stub is expanded, the diagram is expected to contain at least:

- **Schema migrations** — versioned; forward-only for MVP. One component handling migration discovery, lock acquisition, application, and version bookkeeping
- **DAO modules** — one per table:
  - `ObjectiveLifecycleState` — lifecycle_stage, strike_counts, gate_pass_shas, frozen_branch_ref, terminal_disposition, needs_reconcile
  - `TransitionLog` — append-only event log
  - `Sessions` — one row per worker invocation; pending → running → exited → reaped (or crashed)
  - `Leases` — tick lock + supervisor leases; CAS via `(holder_id, fencing_token)`
  - `DependencyEdges` — typed dependency edges between Objectives (sidecar; MVP scope)
  - `MetadataOverrides` — per-Objective config overrides (sidecar; MVP scope)
  - `DiscoveryMarker` — last-seen tracker watermark per adapter
- **Per-tick branch-checkpoint mechanism** — Dolt branch operations; performed at end of every successful tick by the PERSIST phase
- **CAS predicate API surface** — row-version read/write helpers consumed by the [Tick Loop's CAS evaluator component](c4-l3-tick-loop.md)
- **Read-only-cache fallback (likely)** — may service Discovery in `tracker_unreachable` degraded mode by serving from the most recent successful fingerprint snapshot. The degraded-mode handling is ratified in the orchestrator core design; whether it lives as a dedicated cache component or as a code path inside the WorkTracker adapter is an implementation-child decision
- **Backup / archive / pruning policy** — long-term retention story; pruning is post-MVP (see `agents-config-64ecc` for the cryptographic hash-chain that would precede pruning)

## When to expand this stub

When the implementation child for the OrchestratorStateRepo schema and DAO is filed under `wgclw.2` and has:

1. A ratified table-level schema (column types, indices, foreign keys)
2. A concrete decision on the migration mechanism (Alembic-style, raw SQL, custom)
3. A concrete decision on the branch-checkpoint cadence and naming (per-tick branch name pattern)
4. A concrete decision on the read-only-cache invalidation rules

Until then, this stub stays as-is. The table-level structure lives in the [orchestrator core design's State Ownership section](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#state-ownership) and the future [`data-view.md`](data-view.md) artifact.

## Cross-references

- **Container view (L2)**: [c4-l2-container.md](c4-l2-container.md) — places OrchestratorStateRepo as a Dolt-backed data store
- **Tick loop (L3)**: [c4-l3-tick-loop.md](c4-l3-tick-loop.md) — shows the tick loop's interactions with the state-repo client component
- **Data view**: [data-view.md](data-view.md) — what lives where; canonical-ownership boundaries
- **Source spec**: [State Ownership section of the orchestrator core design](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#state-ownership)
