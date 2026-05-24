# PDLC Orchestrator — C4 Level 3: WorkTracker Adapter Components (STUB)

> **Up**: [index](index.md)
> **Sibling L3**: [Tick Loop](c4-l3-tick-loop.md) (fully drawn)
> **Source bead**: `agents-config-wgclw.2.1`
> **Status**: **STUB — not yet drawn**

## Why this file exists

The WorkTracker adapter (bd-bound) is one of the [C4 L2 containers](c4-l2-container.md) inside the `pdlc` process. Its component-level breakdown belongs at L3, alongside the [Tick Loop component diagram](c4-l3-tick-loop.md).

This file is a **placeholder home** for that diagram. It will be filled in when the WorkTracker adapter implementation child (under `wgclw.2`) opens. Establishing the home now means future contributors don't have to invent folder structure mid-stride; drafting the components prematurely would lock in design decisions that the implementation child has not yet ratified.

## Glossary

| Term | Meaning |
|---|---|
| WorkTracker protocol | The contract every tracker adapter must implement; shaped by orchestrator needs (not lowest common denominator). See `CONTEXT.md > WorkTracker` and the [orchestrator core design spec — WorkTracker Protocol](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#the-worktracker-protocol) |
| bd | The reference WorkTracker adapter target — git-backed issue tracker with a Dolt SQL store |
| CAS (Compare-And-Swap) | Concurrency-control: read with version, write only if version unchanged; mismatch aborts and re-reads |
| Version fingerprint | Per-Objective hash (`spec_hash`, `structural_hash`, `dependency_hash`, `lifecycle_status_hash`) used to detect mid-flight tracker edits |
| Discovery marker | Per-adapter watermark recording the last successful tick's position in the tracker's change stream |

## Expected components (pending design ratification)

When this stub is expanded, the diagram is expected to contain at least:

- **Protocol method implementations** — one component per WorkTracker protocol method group (`get_objective` / `bulk_get`, `list_changed_since`, `create_objective`, `set_lifecycle_status`, `set_terminal_disposition`, dependency queries, etc.). Method groups, not one-component-per-method.
- **bd CLI invocation layer** — subprocess management, argument marshalling, output parsing (JSON / text fallback)
- **Tracker-side CAS predicate computation** — reads bd's per-row version (Dolt row-version or equivalent); attaches it to write predicates
- **Adapter-side version-fingerprint computation** — produces `spec_hash`, `structural_hash`, `dependency_hash`, `lifecycle_status_hash` per Objective for the tick loop's RECONCILE phase
- **Error translation** — converts bd-specific errors into protocol-level errors so the tick loop only sees protocol failures (the orchestrator must remain unaware of the adapter's tracker brand)
- **Discovery marker management** — formats and persists the per-adapter marker that drives the acceleration-path Discovery (`list_changed_since(marker)`)

## When to expand this stub

When the implementation child for the WorkTracker adapter is filed under `wgclw.2` and has:

1. A ratified component breakdown of the protocol-method groupings
2. A concrete decision on bd-CLI vs bd-library invocation
3. A concrete decision on fingerprint algorithm (per-field hash composition)
4. A concrete decision on Discovery marker representation (commit hash, `updated_ts` cursor, or hybrid)

Until then, this stub stays as-is. The L2 container diagram and the L3 tick-loop diagram both reference this file as the future home.

## Cross-references

- **Container view (L2)**: [c4-l2-container.md](c4-l2-container.md) — places the WorkTracker adapter as a component inside the `pdlc process` container
- **Tick loop (L3)**: [c4-l3-tick-loop.md](c4-l3-tick-loop.md) — shows the tick loop's interactions with the adapter
- **Source spec**: [WorkTracker Protocol section of the orchestrator core design](../../specs/2026-05-23-pdlc-orchestrator-core-design.md#the-worktracker-protocol)
