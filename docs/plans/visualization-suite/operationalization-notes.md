# Operationalization discussion — decisions log

WORKING NOTE. Running conclusions of the "how does this actually work"
discussion (HANDOFF next-action 1). These decisions feed the F0 section of the
grouped spec. Companion research: `oss-landscape.md`.

## Working model: three provenance tiers

Every datum the suite consumes belongs to one tier; the tiers age differently.

- **Tier 1 — deterministic extracts**: git, `gh` API, beads, graphify. Never
  stale in any interesting sense; regenerate on demand at ~zero cost.
  Reproducible.
- **Tier 2 — agent-inferred facts**: cross-plan edges, synthesized step
  waypoints, recommendations, drill stories. Expensive, unstable across runs;
  the only tier with a real staleness problem.
- **Tier 3 — human verdicts**: accept/reject on inferred facts, annotations,
  work-breakdown decisions. Never regenerated; only ever invalidated (flagged
  when their subject changes), never silently deleted.

V1 (PR-shape) is nearly all Tier 1 plus a small per-PR Tier-2 garnish (drill
stories, hotspot narratives); rebuilt whole per PR. V2 (work-DAG) is
Tier-2-heavy; the pipeline design problem is an inference cache plus a
graduation loop.

## D1 — Persistence of accepted inferred knowledge: hybrid promotion

Decision (Scott): option A.

- **Accepted cross-plan edges are promoted into beads** as real dependency
  edges at accept time — they are dependency facts and must be visible to
  `bd ready`, dispatch, and future sessions. Promoted edges carry a provenance
  marker distinguishing agent-inferred-then-accepted from human-authored.
- **Everything beads cannot express lives in a versioned, repo-committed
  sidecar** keyed by input fingerprints: step waypoints, step→bead-id
  mappings, rejection memory, recommendations, annotations.
- **Rejections persist** alongside acceptances — a rebuild must never
  re-propose an edge the human already rejected (rejection memory is Tier 3).
- Prior art note: Plane and OpenProject both keep a typed edge table
  `{from, to, relation_type}` separate from issue content — same shape.

## D2 — Staleness ladder: escalating checks, human attention last

Decision (Scott): a changed input fingerprint must NOT automatically demand
human reassessment. Most underlying changes do not make a prior inference
incorrect. When change is detected, an agentic check decides which facts are
genuinely in doubt; only those get flagged for human reassessment.

The funnel (each rung strictly cheaper than the next):

1. **Hash check (free)** — input fingerprint unchanged → fact reused verbatim.
2. **Provenance-intersection check (free, mechanical)** — inference-time
   provenance is recorded at passage level (which sections/passages each edge
   relied on). If the diff does not intersect the cited passages →
   auto-restamp against the new fingerprint. [Agent proposal, folded into
   Scott's directive — cheap pre-filter before any model call.]
3. **Agentic doubt check (cheap model)** — claim + cited basis + diff →
   "does this change put the claim in doubt?" No → auto-restamp with an
   audit note (agent-revalidated, date, change hash).
4. **Human reassessment (precious)** — only facts the doubt check flags.
   Surfaced as a reassessment queue; attached Tier-3 verdicts are flagged,
   never silently dropped.

Implication: the inference step must record passage-level citations per edge
at inference time — rung 2 cannot be retrofitted onto an edge whose only
provenance is "read spec X". (Validated pattern: Graphiti bi-temporal edges,
cognee provenance graph, GraphRAG source-chunk FKs.)

## D3 — Regeneration trigger: overnight sweep + on-demand, flag-only

Decision (Scott): option A, flag-only night shift.

- **Primary interface is an on-demand command** ("rebuild the map") — works
  any time, no scheduled machinery required. The overnight sweep is an
  accelerant, never a dependency: if the cron didn't run, the command still
  produces a correct artifact.
- **Overnight scheduled run** does the cheap-but-slow work: Tier-1
  extraction, the full staleness funnel over the sidecar (D2 rungs 1–3), and
  queues doubt flags for morning review.
- **Flag-only**: the night shift does NOT pre-draft replacement inferences.
  Re-inference happens when a human is at the helm (morning triage,
  on-demand), keeping the unattended shift cheap and its output purely
  advisory. This dial can be revisited later without structural change.
- No live server, no polling — regenerated artifacts only (no-fragile-infra
  constraint).

## D4 — Packaging: split by determinism

Decision (Scott): option A.

- **A `packages/` CLI owns everything mechanical**: Tier-1 extractors
  (PyDriller, scc, bd/gh/graphify reads), fingerprint manifests, staleness
  funnel rungs 1–2, sidecar read/write, artifact assembly (data JSON →
  self-contained HTML from template). CI-gated, testable, runs without any
  model.
- **A thin skill owns the agentic parts**: rung-3 doubt checks, edge/step
  inference, review-queue accept/reject flow, promotion into beads. Skill
  tree placement decided by capability-dependency rule (Claude tree if it
  dispatches subagents, shared tree if not).
- **Overnight cron** (D3) calls the CLI plus a cheap-model agentic sweep
  headless.
- Rationale: repo design principles — code over prose; Python over Bash;
  deterministic logic must not burn tokens or live untestable in prose.

## D5 — Annotation round-trip: paste-back baseline + browser-bridge enhancement

Decision (Scott): option A.

- **Baseline (universal)**: every artifact carries the copy-notes-as-JSON
  button (V1 embryo pattern). Works in any browser, any tool, detached from
  any session. Paste into chat = round-trip complete.
- **Enhancement (session-attached, Claude + Chrome extension)**: agent reads
  annotations directly from the open artifact tab via claude-in-chrome
  (`javascript_tool` → localStorage). User says "process my notes"; no paste.
- **No localhost bridge, no file-watcher** — fallback ladder over new
  machinery. File-based ingestion (File System Access API) remains a
  compatible future add-on if unattended night-shift note processing is ever
  wanted; it composes with A without rework.
- Agent processing of notes feeds the existing surfaces: PR comments, bead
  edits, reassessment verdicts, work-breakdown revision proposals.

## D6 — Recommendation timing: batch high-signal, lazy rest

Decision (Scott): option C.

- **Build-time recommendations only where judgment earns its keep**: conflict
  and overlap edges, contested regions, doubt-flagged items, step-vs-backlog
  deltas. Generated during data-build (incl. overnight sweep), so the
  detached morning artifact carries advice where it matters.
- **Plain dependency edges**: evidence only (bead ids, provenance) — no
  canned advice; drill live in an attached session if wanted. Extends
  findings principle #1 (attention bar) to recommendations: don't restate
  the obvious.
- **Recommendations are Tier-2 facts** — same fingerprint cache and D2
  staleness funnel as edges; only changed inputs regenerate.

## Threads resolved by composition (no separate decision needed)

- **Scale (20+ plans)**: fingerprint cache (D2) removes frontier-per-refresh;
  graduation loop (D1) permanently shrinks the Tier-2 surface; flag-only
  night shift (D3) bounds unattended spend; high-signal-only recommendations
  (D6) bound per-build judgment; plan-inclusion filter (F0) bounds rendering.
  C-as-fleet-entry-view stays an evaluation criterion for the spec.
- **Step synthesis vs backlog truth**: step→bead-id mapping lives explicit in
  the D1 sidecar; the step-vs-backlog delta remains a first-class spec
  obligation ("recommend work-breakdown revision" action).

## D7 — V3 deferred thin; two F0 reservations bake in now

Decision (Scott): no V3 brainstorm/prototype before the spec. The grouped
spec's V3 section is written thin — direction + evaluation criteria + a
continuation bead requiring V3's own reaction round before build. F0 carries
two reservations so V3 never forces rework: (a) the scene data contract
supports a time-keyed event stream / snapshot keyframes (Gource-style
minimal events as the intermediate); (b) the scene contract's shared
controls include a timeline-scrub affordance (V2 materialization slider
generalized).

## D8 — Model split for spec + plans

Decision (Scott): Fable banks the judgment-dense inputs
(`spec-judgment-inputs.md`: recommendation taxonomy, contested semantics,
F0 scene-contract skeleton); Opus assembles the grouped spec and writes the
implementation plans from the banked corpus (this file, that file,
`oss-landscape.md`, `findings.md`, HANDOFF decisions). Implementation
planning is mechanical decomposition — no frontier ROI. The spec still runs
the brainstorming skill's review gates regardless of authoring model.

## Candidate vocabulary (glossary decision deferred to spec time)

Promotion (accepted inference → encoded fact), restamp (revalidation against a
new fingerprint without human review), doubt flag, reassessment queue,
rejection memory. `CONTEXT.md` is scoped to the PDLC domain; whether these
terms enter a viz-scoped glossary or live in the spec is decided when the
grouped spec is written.

## Status

All seven HANDOFF operationalization threads resolved (D1–D6 + composition
notes above). Conclusions feed the grouped spec's F0 section. Next per
HANDOFF: V3 brainstorm (lighter), then the grouped spec.
