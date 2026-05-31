# ADR-0001: Holding Place is a peer subsystem of the PDLC Orchestrator

**Status**: Accepted (2026-05-25)

## Context

The PDLC architecture distinguishes two primitives:

- **Idea** — a human-curated possibility that lives in a workspace called the Holding Place, where it is captured, groomed across buckets, possibly shaped via brainstorming, and either promoted into work or killed with an epitaph
- **Objective** — a unit of work tracked by the PDLC orchestrator's deterministic finite-state machine, which traverses lifecycle stages from `CANDIDATE_UOW` through to a terminal state (`MERGED`, `KILLED`, or `PARKED`)

The project's domain glossary (`CONTEXT.md > Holding Place`) had already pinned the Holding Place as "a peer service, NOT owned by the Orchestrator," and had specified the orchestrator's interactions with it as **exactly two** operations: `promote(idea_id) → objective_id` and `create_idea(provenance.decomposition_of=<container_id>)`.

However, the PDLC Design Phase epic claimed Holding Place persistence, Capture protocol, Provenance Backreference, Grooming ceremony UX, buckets, the grooming nag, Cool Idea Quarantine UX, and the Idea Curator persona — all as in-scope. This put the Idea pipeline architecturally inside the Design Phase, which is a post-Promote stage of the Orchestrator's FSM.

The contradiction surfaced during the tracer-scoping work for Scenario 1 (happy-path Idea→MERGED). The tracer literally needs a Holding Place that can hold an Idea and respond to `promote`. If the Holding Place lives inside an Orchestrator-owned epic, then the orchestrator-to-Holding-Place call collapses into an internal function call and the "exactly two" boundary disappears, re-importing the entanglement the architecture is explicitly trying to avoid.

Two options were considered.

## Considered alternatives

### Option α — Holding Place as a peer subsystem to the PDLC Orchestrator

A separate epic owns the Idea pipeline end-to-end, including storage, persona, UX, and the two orchestrator-facing operations. The orchestrator and the Holding Place communicate via a documented contract.

### Option β — Holding Place absorbed into the PDLC Orchestrator's Design Phase epic

The Idea pipeline is implemented as a Design-Phase responsibility, treating the Idea/Objective distinction as a label rather than a structural boundary. The "exactly two" operations become internal method calls.

## Decision

**Option α — Holding Place is a peer subsystem.**

This is structurally honoured by:

- A dedicated **PDLC Holding Place** epic, sibling to the Orchestrator's epics, owning the Idea pipeline (Capture, Grooming, Shape, Promote, Killed-with-Epitaph), storage abstraction, and Idea-side personas (Idea Curator)
- A **storage adapter seam** in the Holding Place, parallel to the Orchestrator's WorkTracker adapter: MVP backend is filesystem (likely YAML-per-Idea); future backends (Dolt, SQLite, Postgres, cloud KV) swap by configuration rather than code rewrite
- A **Promote contract spec** as its own first-class artifact, owned by the Holding Place epic. The contract covers both `promote(idea_id) → objective_id` and `create_idea(provenance.decomposition_of=<container_id>)`, including idempotency semantics, fingerprint propagation (`originating_idea_id` carries onto the resulting Objective), error taxonomy, transaction boundaries, and a reference Python stub the tracer can bind against
- The Design Phase epic's scope was amended to begin at `CANDIDATE_UOW` — i.e., post-Promote — and to call out the Holding Place as out-of-scope with an explicit cross-reference

## Consequences

**Positive**

- The "exactly two" boundary becomes a hard architectural seam rather than a soft convention. The orchestrator cannot accidentally absorb Idea-pipeline behavior because the operations cross a process / interface boundary that resists code-level encroachment
- Pluggable storage at the Holding Place is symmetric with the Orchestrator's WorkTracker adapter — one architectural pattern, applied twice
- The tracer scenario has a clean contract to bind against. Without this resolution, the tracer would have had to either fake an internal interface or push test seams into the orchestrator's internals
- Each side can evolve at its own pace. The Idea pipeline's UX surface (grooming, brainstorm-quarantine, buckets) lives where it can be iterated on without rippling into the FSM engine

**Negative**

- One more epic to coordinate. Cross-epic seams require explicit contract beads; the Promote contract is the first
- The contract becomes a versioning surface. Future changes to the Idea or Objective primitives must consider compatibility on both sides of the call
- The "Idea pipeline" surface area is now distributed across the Holding Place epic + the brainstorming UX inside the discipline layer. Care is needed to keep the seam from drifting between them

**Risks accepted**

- Brainstorming-as-UX continues to live in the discipline layer (skills), which physically straddles the Holding Place. The architecture treats brainstorming as a thin UX over Holding Place primitives; if this turns out to be load-bearing wrong, the seam will move. Tracked in the far-horizon register
- The first iteration of the Promote contract will probably get the idempotency semantics wrong on the first try. The cost of revision is bounded because there is only one caller (the orchestrator) and one implementer (the Holding Place); not a cross-tool contract

## Provenance

Decided during the PDLC tracer-scoping grill session of 2026-05-25, after a focused sweep of the Orchestrator's sibling epics revealed that the Design Phase epic's scope contradicted the domain glossary on this specific boundary. The session also surfaced a broader set of cross-epic seams and persona gaps that were intentionally deferred to a far-horizon register rather than being acted on in the same surgery — to keep the near-horizon path to the tracer narrow.
